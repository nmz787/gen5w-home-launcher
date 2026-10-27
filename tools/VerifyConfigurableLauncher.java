// Independently reverse only the audited menu hook/resource substitutions and
// the one generic launcher click dispatcher replacement, then
// compare every original class canonically. Extra/removed classes and changes
// to fields, metadata, methods or unrelated instructions fail closed.
import java.io.*;
import java.util.*;
import java.nio.file.*;
import org.jf.dexlib2.*;
import org.jf.dexlib2.analysis.*;
import org.jf.dexlib2.iface.*;
import org.jf.dexlib2.iface.instruction.*;
import org.jf.dexlib2.iface.reference.*;
import org.jf.dexlib2.immutable.*;
import org.jf.dexlib2.immutable.reference.*;
import org.jf.dexlib2.builder.*;
import org.jf.dexlib2.builder.instruction.*;
import org.jf.dexlib2.writer.pool.*;
import org.jf.dexlib2.writer.io.*;
class VerifyConfigurableLauncher {
 static final Opcodes API=Opcodes.forApi(19);
 static String editorList="cu";
 static final String HELPER="Lcom/android/launcher3/configurable/TileRegistry;";
 static final String NAMESPACE="Lcom/android/launcher3/configurable/";
 static final String CLICK_OWNER="Lcom/android/launcher3/view/bp;";
 static final String OEM_DISPATCH="Lcom/android/launcher3/utils/a;";
 static final Map<String,String[]> WRAPPERS=Map.of(
  "contextString",new String[]{"Landroid/content/Context;","getString","Ljava/lang/String;"},
  "resourceString",new String[]{"Landroid/content/res/Resources;","getString","Ljava/lang/String;"},
  "resourceText",new String[]{"Landroid/content/res/Resources;","getText","Ljava/lang/CharSequence;"},
  "drawable",new String[]{"Landroid/content/res/Resources;","getDrawable","Landroid/graphics/drawable/Drawable;"},
  "setText",new String[]{"Landroid/widget/TextView;","setText","V"},
  "setImageResource",new String[]{"Landroid/widget/ImageView;","setImageResource","V"},
  "decodeResource",new String[]{"Landroid/graphics/BitmapFactory;","decodeResource","Landroid/graphics/Bitmap;"});
 static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
 static Map<String,ClassDef> classes(DexFile dex){var map=new TreeMap<String,ClassDef>();for(var c:dex.getClasses())map.put(c.getType(),c);return map;}
 static byte[] bytes(ClassDef c)throws Exception{var store=new MemoryDataStore();DexPool.writeTo(store,new ImmutableDexFile(API,List.of(c)));return store.getData();}
 static ClassDef normalize(ClassDef cls,boolean editor,int[] counts,Set<String> changedMethods){
  var methods=new ArrayList<Method>();
  for(var method:cls.getMethods()){
   var impl=method.getImplementation();boolean touched=false;
   if(impl!=null){
    var mut=new MutableMethodImplementation(impl);
    for(int i=mut.getInstructions().size()-1;i>=0;i--){
     var instruction=mut.getInstructions().get(i);
     require(!instruction.getOpcode().odexOnly(),"Optimized instruction remains: "+method);
     if(!(instruction instanceof ReferenceInstruction ri)||!(ri.getReference() instanceof MethodReference ref)||!ref.getDefiningClass().equals(HELPER))continue;
     require(instruction.getOpcode()==Opcode.INVOKE_STATIC && instruction instanceof FiveRegisterInstruction,"Unexpected helper invocation: "+method);
     var regs=(FiveRegisterInstruction)instruction;
     if(ref.getName().equals("append")){
      String owner=editor?"Lcom/hkmc/system/app/homesetting/allmenuedit/z;":"Lcom/android/launcher3/view/a/g;";
      require(cls.getType().equals(owner)&&method.getName().equals("load")&&ref.getParameterTypes().equals(List.of("Ljava/lang/Object;"))&&ref.getReturnType().equals("V")&&regs.getRegisterCount()==1&&i>0,"Unexpected append hook");
      var previous=mut.getInstructions().get(i-1);
      require(previous.getOpcode()==(editor?Opcode.SPUT_OBJECT:Opcode.IPUT_OBJECT)&&previous instanceof ReferenceInstruction,"Hook not immediately after OEM list assignment");
      var field=(FieldReference)((ReferenceInstruction)previous).getReference();
      require(field.getDefiningClass().equals(owner)&&field.getName().equals(editor?editorList:"by"),"Wrong OEM list field");
      int register=editor?impl.getRegisterCount()-1:((TwoRegisterInstruction)previous).getRegisterB();
      require(regs.getRegisterC()==register,"Wrong append owner register");
      mut.removeInstruction(i);counts[0]++;
     }else if(ref.getName().equals("launch")){
      require(!editor&&cls.getType().equals(CLICK_OWNER)&&method.getName().equals("onClick")
       &&method.getParameterTypes().equals(List.of("Landroid/view/View;"))&&method.getReturnType().equals("V"),"Dispatch hook outside audited launcher click handler");
      require(regs.getRegisterCount()==1&&ref.getParameterTypes().equals(List.of("Landroid/content/Intent;"))&&ref.getReturnType().equals("V"),"Unexpected launch wrapper signature");
      var originalRef=new ImmutableMethodReference(OEM_DISPATCH,"b",List.of("Landroid/content/Intent;"),"V");
      mut.replaceInstruction(i,new BuilderInstruction35c(Opcode.INVOKE_STATIC,1,regs.getRegisterC(),0,0,0,0,originalRef));counts[2]++;
     }else{
      var original=WRAPPERS.get(ref.getName());require(original!=null,"Unknown helper call: "+ref);
      require(regs.getRegisterCount()==2&&ref.getParameterTypes().equals(List.of(original[0],"I"))&&ref.getReturnType().equals(original[2]),"Unexpected resource-wrapper signature");
      var originalRef=new ImmutableMethodReference(original[0],original[1],List.of("I"),original[2]);
      mut.replaceInstruction(i,new BuilderInstruction35c(Opcode.INVOKE_VIRTUAL,2,regs.getRegisterC(),regs.getRegisterD(),0,0,0,originalRef));counts[1]++;
     }
     touched=true;
    }
    if(touched)impl=mut;
   }
   if(touched)changedMethods.add(method.toString());
   methods.add(new ImmutableMethod(method.getDefiningClass(),method.getName(),method.getParameters(),method.getReturnType(),method.getAccessFlags(),method.getAnnotations(),method.getHiddenApiRestrictions(),impl));
  }
  return new ImmutableClassDef(cls.getType(),cls.getAccessFlags(),cls.getSuperclass(),cls.getInterfaces(),cls.getSourceFile(),cls.getAnnotations(),cls.getFields(),methods);
 }
 static void reflectionContract(Map<String,ClassDef> source,boolean editor){
  String owner=editor?"Lcom/hkmc/system/app/homesetting/allmenuedit/z;":"Lcom/android/launcher3/view/a/g;";
  String entry=editor?"Lcom/hkmc/system/app/homesetting/allmenuedit/c;":"Lcom/android/launcher3/view/a/Q;";
  require(source.containsKey(owner)&&source.containsKey(entry),"OEM owner/model missing");
  var fields=new HashMap<String,Field>();for(var f:source.get(owner).getFields())fields.put(f.getName(),f);
  require(fields.containsKey("mContext")&&fields.get("mContext").getType().equals("Landroid/content/Context;"),"Declared owner mContext differs");
  if(editor){
   require(fields.containsKey("cu")!=fields.containsKey("cs"),"Ambiguous or unknown editor list profile");
   editorList=fields.containsKey("cs")?"cs":"cu";
  }
  var list=fields.get(editor?editorList:"by");require(list!=null&&Set.of("Ljava/util/List;","Ljava/util/ArrayList;").contains(list.getType()),"Declared owner list field differs");
  require(((list.getAccessFlags()&AccessFlags.STATIC.getValue())!=0)==editor,"OEM list static/instance identity differs");
  boolean ctor=false,packageName=false,className=false;
  for(var m:source.get(entry).getMethods()){
   if((m.getAccessFlags()&AccessFlags.PUBLIC.getValue())==0)continue;
   if(m.getName().equals("<init>")&&m.getParameterTypes().equals(List.of(owner,"Landroid/content/Context;","Ljava/lang/String;","Ljava/lang/String;","I","I","I"))&&m.getReturnType().equals("V"))ctor=true;
   if(m.getParameterTypes().isEmpty()&&m.getReturnType().equals("Ljava/lang/String;")){
    if(m.getName().equals("getPackageName"))packageName=true;
    if(m.getName().equals("getClassName"))className=true;
   }
  }
  require(ctor&&packageName&&className,"Public entry constructor/accessor reflection contract differs");
  System.out.println("Physical reflection contract passed: declared mContext and "+(editor?"static "+editorList:"instance by")+", exact public entry constructor and getPackageName/getClassName.");
 }
 static void clickContract(Map<String,ClassDef> source,boolean editor){
  if(editor)return;
  var cls=source.get(CLICK_OWNER);require(cls!=null,"Audited launcher click class missing");
  int dispatches=0;
  for(var method:cls.getMethods()){
   if(!method.getName().equals("onClick")||!method.getParameterTypes().equals(List.of("Landroid/view/View;"))||!method.getReturnType().equals("V"))continue;
   require(method.getImplementation()!=null,"Launcher click method has no implementation");
   for(var instruction:method.getImplementation().getInstructions()){
    if(instruction instanceof ReferenceInstruction ri&&ri.getReference() instanceof MethodReference ref
     &&ref.getDefiningClass().equals(OEM_DISPATCH)&&ref.getName().equals("b")
     &&ref.getParameterTypes().equals(List.of("Landroid/content/Intent;"))&&ref.getReturnType().equals("V")){
     require(instruction.getOpcode()==Opcode.INVOKE_STATIC&&instruction instanceof FiveRegisterInstruction
      &&((FiveRegisterInstruction)instruction).getRegisterCount()==1,"Unexpected OEM dispatch call form");dispatches++;
    }
   }
  }
  require(dispatches==1,"Expected exactly one original generic MAIN/LAUNCHER dispatch in audited click handler");
  System.out.println("Source click contract passed: exactly one utils.a.b(Intent) static call in view.bp.onClick(View).");
 }
 public static void main(String[]args)throws Exception{
  if(args.length<4||args.length>5)throw new IllegalArgumentException("original.dex patched.dex helper.dex framework-dir [--home-setting]");
  boolean editor=args.length==5&&args[4].equals("--home-setting");
  var original=DexFileFactory.loadDexFile(new File(args[0]),API);var patched=DexFileFactory.loadDexFile(new File(args[1]),API);var helper=DexFileFactory.loadDexFile(new File(args[2]),API);
  var before=classes(original);var after=classes(patched);var helpers=classes(helper);reflectionContract(before,editor);clickContract(before,editor);
  require(helpers.containsKey(HELPER),"Registry main class absent from compiled helper DEX");
  for(var name:helpers.keySet()){
   require(name.startsWith(NAMESPACE),"Helper outside configurable namespace: "+name);
   require(!before.containsKey(name),"Helper collides with original class: "+name);
  }
  var inventory=new TreeSet<String>(before.keySet());inventory.addAll(helpers.keySet());require(after.keySet().equals(inventory),"Unexpected class additions or removals");
  for(var name:helpers.keySet())require(Arrays.equals(bytes(helpers.get(name)),bytes(after.get(name))),"Helper differs: "+name);
  int[] counts={0,0,0};var changed=new TreeSet<String>();var changedMethods=new TreeSet<String>();
  for(var name:before.keySet()){
   var a=before.get(name);var b=after.get(name);
   if(!Arrays.equals(bytes(a),bytes(b)))changed.add(name);
   var restored=normalize(b,editor,counts,changedMethods);
   require(Arrays.equals(bytes(a),bytes(restored)),"Unapproved change survives reversal: "+name);
  }
  require(counts[0]==1&&counts[1]>0,"Missing intended menu/resource changes");
  require(counts[2]==(editor?0:1),"Expected exactly one launcher click dispatcher hook and none in editor");
  for(var name:changed)System.out.println("Changed class: "+name);
  for(var method:changedMethods)System.out.println("Changed method: "+method);
  System.out.println("Structural comparison: "+before.size()+" original classes, "+changed.size()+" changed, "+(before.size()-changed.size())+" unchanged, "+helpers.size()+" exact helper classes; append="+counts[0]+", resource substitutions="+counts[1]+", click dispatch="+counts[2]);
  var providers=new ArrayList<ClassProvider>();providers.add(new DexClassProvider(patched));
  try(var files=Files.list(Path.of(args[3]))){for(var p:files.sorted().toList())if(p.toString().endsWith(".odex"))providers.add(new DexClassProvider(DexFileFactory.loadDexFile(p.toFile(),API)));}
  var cp=new ClassPath(providers,false,ClassPath.NOT_ART);int analyzed=0;
  for(var cls:patched.getClasses())for(var method:cls.getMethods())if(method.getImplementation()!=null&&(changedMethods.contains(method.toString())||helpers.containsKey(cls.getType()))){
   var analyzer=new MethodAnalyzer(cp,method,null,false);require(analyzer.getAnalysisException()==null,"Dalvik analysis failed: "+method+" "+analyzer.getAnalysisException());analyzed++;
  }
  System.out.println("Dalvik analysis passed: "+analyzed+" changed/helper methods against supplied physical firmware definitions. No runtime UI/vehicle test.");
 }
}
