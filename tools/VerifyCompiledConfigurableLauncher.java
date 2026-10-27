// Verify the native emitted/reconstructed DEX against the host patched DEX.
// Normalize only context-specific whitelisted helper inherited-member owners,
// prove their declarations against the physical class hierarchy, then compare
// all class bytes canonically. Require exactly the Dalvik class flags
// CLASS_ISPREVERIFIED(1<<16) | CLASS_ISOPTIMIZED(1<<17) added to each changed helper.
// AOSP android-4.4_r1 vm/oo/Object.h explicitly permits these in optimized DEX.
// No behavior/instruction/register normalization.
import java.io.*;import java.nio.file.*;import java.util.*;
import org.jf.dexlib2.*;import org.jf.dexlib2.analysis.*;
import org.jf.dexlib2.iface.*;import org.jf.dexlib2.iface.instruction.*;
import org.jf.dexlib2.iface.reference.*;import org.jf.dexlib2.immutable.*;
import org.jf.dexlib2.builder.*;import org.jf.dexlib2.builder.instruction.*;
import org.jf.dexlib2.writer.io.*;import org.jf.dexlib2.writer.pool.*;
class VerifyCompiledConfigurableLauncher {
 static final Opcodes API=Opcodes.forApi(19);
 static final String TILE="Lcom/android/launcher3/configurable/TileRegistry;";
 static final String ICON=TILE.substring(0,TILE.length()-1)+"$TileIcon;";
 static final String DRAWABLE="Landroid/graphics/drawable/Drawable;";
 static final String NAMESPACE="Lcom/android/launcher3/configurable/";
 static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
 static Map<String,ClassDef> classes(DexFile dex){var result=new TreeMap<String,ClassDef>();for(var c:dex.getClasses())result.put(c.getType(),c);return result;}
 static String methodKey(MethodReference m){return m.getName()+m.getParameterTypes()+m.getReturnType();}
 static byte[] bytes(ClassDef cls)throws Exception{var store=new MemoryDataStore();DexPool.writeTo(store,new ImmutableDexFile(API,List.of(cls)));return store.getData();}
 static ClassDef definition(ClassPath cp,String owner){return ((ClassProto)cp.getClass(owner)).getClassDef();}
 static String methodOwner(ClassPath cp,MethodReference ref){
  String owner=ref.getDefiningClass();var visited=new HashSet<String>();
  while(owner!=null){require(visited.add(owner),"Cyclic class hierarchy");var cls=definition(cp,owner);
   for(var m:cls.getMethods())if(methodKey(m).equals(methodKey(ref)))return m.getDefiningClass();owner=cls.getSuperclass();
  }throw new AssertionError("Unresolved method "+ref);
 }
 static String fieldOwner(ClassPath cp,FieldReference ref){
  String owner=ref.getDefiningClass();var visited=new HashSet<String>();
  while(owner!=null){require(visited.add(owner),"Cyclic field hierarchy");var cls=definition(cp,owner);
   for(var f:cls.getFields())if(f.getName().equals(ref.getName())&&f.getType().equals(ref.getType()))return f.getDefiningClass();owner=cls.getSuperclass();
  }throw new AssertionError("Unresolved field "+ref);
 }
 static boolean permitted(Method method,MethodReference expected,MethodReference actual){
  if(!methodKey(expected).equals(methodKey(actual)))return false;
  String context=method.getDefiningClass(),key=methodKey(method);
  if(context.equals(TILE.substring(0,TILE.length()-1)+"$Job;")&&key.equals("run[]V")){
   if(expected.getDefiningClass().equals("Ljava/io/BufferedReader;")&&actual.getDefiningClass().equals("Ljava/io/Reader;")&&methodKey(expected).equals("read[[C]I"))return true;
   if(expected.getDefiningClass().equals("Ljava/io/Writer;")&&actual.getDefiningClass().equals("Ljava/io/OutputStreamWriter;"))
    return Set.of("write[[C, I, I]V","flush[]V","close[]V").contains(methodKey(expected));
  }
  if(context.equals(TILE)&&key.equals("load[]V")&&expected.getDefiningClass().equals("Ljava/io/FileInputStream;")&&actual.getDefiningClass().equals("Ljava/io/InputStream;")&&methodKey(expected).equals("read[[B]I"))return true;
  if(context.equals(TILE)&&key.equals("setImageResource[Landroid/widget/ImageView;, I]V")&&expected.getDefiningClass().equals("Landroid/widget/ImageView;")&&actual.getDefiningClass().equals("Landroid/view/View;")&&methodKey(expected).equals("getResources[]Landroid/content/res/Resources;"))return true;
  if(context.equals(ICON)&&expected.getDefiningClass().equals(ICON)&&actual.getDefiningClass().equals(DRAWABLE)){
   String member=methodKey(expected);
   return switch(key){
    case "draw[Landroid/graphics/Canvas;]V" -> Set.of("getBounds[]Landroid/graphics/Rect;","isVisible[]Z","getCallback[]Landroid/graphics/drawable/Drawable$Callback;","scheduleSelf[Ljava/lang/Runnable;, J]V").contains(member);
    case "setAlpha[I]V", "setColorFilter[Landroid/graphics/ColorFilter;]V", "run[]V" -> member.equals("invalidateSelf[]V");
    case "setVisible[Z, Z]Z" -> member.equals("unscheduleSelf[Ljava/lang/Runnable;]V");
    default -> false;
   };
  }
  return context.equals(TILE)&&key.equals("append[Ljava/lang/Object;]V")
   && expected.getDefiningClass().equals("Ljava/lang/reflect/Field;")
   && actual.getDefiningClass().equals("Ljava/lang/reflect/AccessibleObject;")
   && methodKey(expected).equals("setAccessible[Z]V");
 }
 static boolean permitted(Method method,FieldReference expected,FieldReference actual){
  return method.getDefiningClass().equals(TILE)&&methodKey(method).equals("append[Ljava/lang/Object;]V")
   &&expected.getDefiningClass().equals("Landroid/content/pm/ActivityInfo;")&&actual.getDefiningClass().equals("Landroid/content/pm/ComponentInfo;")
   &&expected.getName().equals(actual.getName())&&expected.getType().equals(actual.getType())
   &&((expected.getName().equals("enabled")||expected.getName().equals("exported"))&&expected.getType().equals("Z")||expected.getName().equals("applicationInfo")&&expected.getType().equals("Landroid/content/pm/ApplicationInfo;"));
 }
 static ClassDef normalize(ClassDef expected,ClassDef actual,ClassPath cp,Map<String,Integer> counts){
  require((expected.getAccessFlags()&0x30000)==0&&actual.getAccessFlags()==(expected.getAccessFlags()|0x30000),"Unexpected helper native class access flags: "+actual.getType()+" "+actual.getAccessFlags());
  System.out.println("Proved Dalvik compilation class flags: "+actual.getType()+" adds exactly CLASS_ISPREVERIFIED|CLASS_ISOPTIMIZED (0x30000)");
  var originals=new HashMap<String,Method>();for(var m:expected.getMethods())originals.put(methodKey(m),m);
  var methods=new ArrayList<Method>();
  for(var method:actual.getMethods()){
   MethodImplementation impl=method.getImplementation();var old=originals.remove(methodKey(method));require(old!=null,"Added native method "+method);
   if(impl!=null&&old.getImplementation()!=null){
    var original=new ArrayList<Instruction>();old.getImplementation().getInstructions().forEach(original::add);
    var mut=new MutableMethodImplementation(impl);require(mut.getInstructions().size()==original.size(),"Native instruction inventory changed: "+method);
    boolean changed=false;
    for(int n=0;n<original.size();n++){
     var a=original.get(n);var b=mut.getInstructions().get(n);
     require(!b.getOpcode().odexOnly(),"Optimized instruction remains in reconstructed native DEX");
     if(a.getOpcode()!=b.getOpcode()||!(a instanceof ReferenceInstruction ar)||!(b instanceof ReferenceInstruction br)||ar.getReference().equals(br.getReference()))continue;
     if(ar.getReference() instanceof MethodReference e&&br.getReference() instanceof MethodReference r&&permitted(method,e,r)){
      require(a.getOpcode()==Opcode.INVOKE_VIRTUAL&&b instanceof FiveRegisterInstruction,"Inherited helper call opcode changed");
      var regs=(FiveRegisterInstruction)b;
      if(e.getDefiningClass().equals("Ljava/io/Writer;")&&r.getDefiningClass().equals("Ljava/io/OutputStreamWriter;")){
       // dexopt binds the receiver's override; prove that receiver at this exact
       // call rather than treating arbitrary subclass owner changes as equal.
       var analyzer=new MethodAnalyzer(cp,old,null,false);
       require(analyzer.getAnalysisException()==null,"Cannot prove Writer receiver: "+analyzer.getAnalysisException());
       var receiver=analyzer.getAnalyzedInstructions().get(n).getPreInstructionRegisterType(regs.getRegisterC());
       require(receiver.category==RegisterType.REFERENCE&&receiver.type.getType().equals("Ljava/io/OutputStreamWriter;"),"Writer call receiver is not exactly OutputStreamWriter: "+receiver);
       require(definition(cp,"Ljava/io/OutputStreamWriter;").getSuperclass().equals("Ljava/io/Writer;"),"OutputStreamWriter superclass differs");
       require(methodOwner(cp,e).equals("Ljava/io/Writer;")&&methodOwner(cp,r).equals("Ljava/io/OutputStreamWriter;"),"Captured framework does not prove Writer override declarations");
       System.out.println("Proved concrete OutputStreamWriter receiver: "+method+" instruction="+n+" register="+regs.getRegisterC());
      }else require(methodOwner(cp,e).equals(r.getDefiningClass())&&methodOwner(cp,r).equals(r.getDefiningClass()),"Physical inheritance does not justify method-owner resolution: "+e+" -> "+r);
      mut.replaceInstruction(n,new BuilderInstruction35c(b.getOpcode(),regs.getRegisterCount(),regs.getRegisterC(),regs.getRegisterD(),regs.getRegisterE(),regs.getRegisterF(),regs.getRegisterG(),e));
      counts.merge(e.getName(),1,Integer::sum);changed=true;
      System.out.println("Proved inherited method owner: "+method+" instruction="+n+" "+e+" -> "+r);
     }else if(ar.getReference() instanceof FieldReference e&&br.getReference() instanceof FieldReference r&&permitted(method,e,r)){
      require((b.getOpcode()==Opcode.IGET_BOOLEAN||b.getOpcode()==Opcode.IGET_OBJECT)&&b instanceof TwoRegisterInstruction,"Inherited helper field opcode changed");
      require(fieldOwner(cp,e).equals(r.getDefiningClass())&&fieldOwner(cp,r).equals(r.getDefiningClass()),"Physical inheritance does not justify field-owner resolution: "+e+" -> "+r);
      var regs=(TwoRegisterInstruction)b;mut.replaceInstruction(n,new BuilderInstruction22c(b.getOpcode(),regs.getRegisterA(),regs.getRegisterB(),e));
      counts.merge(e.getName(),1,Integer::sum);changed=true;
      System.out.println("Proved inherited field owner: "+method+" instruction="+n+" "+e+" -> "+r);
     }
    }
    if(changed)impl=mut;
   }
   methods.add(new ImmutableMethod(method.getDefiningClass(),method.getName(),method.getParameters(),method.getReturnType(),method.getAccessFlags(),method.getAnnotations(),method.getHiddenApiRestrictions(),impl));
  }
  require(originals.isEmpty(),"Native methods removed");
  return new ImmutableClassDef(actual.getType(),expected.getAccessFlags(),actual.getSuperclass(),actual.getInterfaces(),actual.getSourceFile(),actual.getAnnotations(),actual.getFields(),methods);
 }
 public static void main(String[]args)throws Exception{
  if(args.length!=3)throw new IllegalArgumentException("patched.dex native-reconstructed.dex physical-framework-dir");
  var expected=DexFileFactory.loadDexFile(new File(args[0]),API);var actual=DexFileFactory.loadDexFile(new File(args[1]),API);
  var before=classes(expected);var after=classes(actual);require(before.keySet().equals(after.keySet()),"Native class inventory changed");
  var providers=new ArrayList<ClassProvider>();providers.add(new DexClassProvider(actual));
  try(var paths=Files.list(Path.of(args[2]))){for(var path:paths.sorted().toList())if(path.toString().endsWith(".odex"))providers.add(new DexClassProvider(DexFileFactory.loadDexFile(path.toFile(),API)));}
  var cp=new ClassPath(providers,false,ClassPath.NOT_ART);var counts=new TreeMap<String,Integer>();int exact=0,normalized=0;
  for(var name:before.keySet()){
   var a=before.get(name);var b=after.get(name);
   if(name.startsWith(NAMESPACE))require((a.getAccessFlags()&0x30000)==0&&b.getAccessFlags()==(a.getAccessFlags()|0x30000),"Unexpected helper native class access flags: "+name);
   if(Arrays.equals(bytes(a),bytes(b))){exact++;continue;}
   require(name.startsWith(NAMESPACE),"Unexpected native change outside compiled helper namespace: "+name);
   require(Arrays.equals(bytes(a),bytes(normalize(a,b,cp,counts))),"Unapproved native change after narrowly proved inheritance normalization: "+name);normalized++;
  }
  require(normalized>0,"Expected native verification flags on compiled helper classes");
  System.out.println("Audited inherited-member owner resolutions: "+counts);
  System.out.println("Compiled class comparison passed: "+before.size()+" classes; "+exact+" canonical-identical; "+normalized+" helper classes differ only in narrowly whitelisted and hierarchy-proved inherited-member owners and the required Dalvik preverified/optimized class flags (0x30000 each). Registers, opcodes, branches, try/debug items, fields/method metadata and all other references unchanged.");
 }
}
