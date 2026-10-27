// Add a tile to the OEM menu model and resolve its private title/icon keys.
import java.io.*;
import java.util.*;
import org.jf.dexlib2.*;
import org.jf.dexlib2.iface.*;
import org.jf.dexlib2.iface.instruction.*;
import org.jf.dexlib2.iface.reference.*;
import org.jf.dexlib2.immutable.*;
import org.jf.dexlib2.immutable.reference.*;
import org.jf.dexlib2.builder.*;
import org.jf.dexlib2.builder.instruction.*;
class PatchConfigurableLauncher {
 static final String HELPER="Lcom/android/launcher3/configurable/TileRegistry;";
 static ImmutableMethodReference ref(String name,String result,String...parameters) {
  return new ImmutableMethodReference(HELPER,name,List.of(parameters),result);
 }
 static BuilderInstruction35c call(MethodReference method,int...registers) {
  int[] r=Arrays.copyOf(registers,5);
  return new BuilderInstruction35c(Opcode.INVOKE_STATIC,registers.length,r[0],r[1],r[2],r[3],r[4],method);
 }
 public static void main(String[] args) throws Exception {
  boolean homeSetting=args.length>3 && args[3].equals("--home-setting");
  var dex=DexFileFactory.loadDexFile(new File(args[0]),Opcodes.forApi(19));
  var helper=DexFileFactory.loadDexFile(new File(args[1]),Opcodes.forApi(19));
  List<ClassDef> classes=new ArrayList<>(); int hooks=0,strings=0,drawables=0,dispatch=0;
  for(var cls:dex.getClasses()) {
   if(cls.getType().startsWith("Lcom/android/launcher3/configurable/")) throw new IOException("Already patched");
   List<Method> methods=new ArrayList<>();
   for(var method:cls.getMethods()) {
    MethodImplementation impl=method.getImplementation();
    if(impl!=null) {
     var mut=new MutableMethodImplementation(impl);
     for(int i=mut.getInstructions().size()-1;i>=0;i--) {
      var ins=mut.getInstructions().get(i);
      boolean targetOwner=homeSetting ? cls.getType().equals("Lcom/hkmc/system/app/homesetting/allmenuedit/z;")
       : cls.getType().equals("Lcom/android/launcher3/view/a/g;");
      if(targetOwner && method.getName().equals("load")
       && (homeSetting ? ins.getOpcode()==Opcode.SPUT_OBJECT : ins.getOpcode()==Opcode.IPUT_OBJECT)
       && ins instanceof ReferenceInstruction ri && ri.getReference() instanceof FieldReference f
       && f.getDefiningClass().equals(cls.getType())
       && (homeSetting?Set.of("cu","cs").contains(f.getName()):f.getName().equals("by"))) {
       int owner=homeSetting ? method.getImplementation().getRegisterCount()-1 : ((TwoRegisterInstruction)ins).getRegisterB();
       mut.addInstruction(i+1,call(ref("append","V","Ljava/lang/Object;"),owner)); hooks++;
      }
      if(!homeSetting && cls.getType().equals("Lcom/android/launcher3/view/bp;") && method.getName().equals("onClick")
       && ins.getOpcode()==Opcode.INVOKE_STATIC && ins instanceof ReferenceInstruction clickRef
       && clickRef.getReference() instanceof MethodReference click
       && click.getDefiningClass().equals("Lcom/android/launcher3/utils/a;") && click.getName().equals("b")
       && click.getParameterTypes().equals(List.of("Landroid/content/Intent;")) && click.getReturnType().equals("V")) {
       var regs=(FiveRegisterInstruction)ins;
       if(regs.getRegisterCount()!=1)throw new IOException("Unexpected dispatch registers");
       mut.replaceInstruction(i,call(ref("launch","V","Landroid/content/Intent;"),regs.getRegisterC())); dispatch++;
      }
      if(ins.getOpcode()!=Opcode.INVOKE_VIRTUAL || !(ins instanceof ReferenceInstruction ri)
       || !(ri.getReference() instanceof MethodReference m) || !m.getParameterTypes().equals(List.of("I"))) continue;
      String type=m.getDefiningClass(),name=m.getName(); String replacement=null;
      if(type.equals("Landroid/content/Context;") && name.equals("getString")) replacement="contextString";
      if(type.equals("Landroid/content/res/Resources;")) {
       if(name.equals("getString")) replacement="resourceString";
       if(name.equals("getText")) replacement="resourceText";
       if(name.equals("getDrawable")) replacement="drawable";
      }
      if(type.equals("Landroid/widget/TextView;") && name.equals("setText")) replacement="setText";
      if(type.equals("Landroid/widget/ImageView;") && name.equals("setImageResource")) replacement="setImageResource";
      if(type.equals("Landroid/graphics/BitmapFactory;") && name.equals("decodeResource")) replacement="decodeResource";
      if(replacement!=null) {
       var regs=(FiveRegisterInstruction)ins;
       if(regs.getRegisterCount()!=2) throw new IOException("Unexpected call registers");
       mut.replaceInstruction(i,call(ref(replacement,m.getReturnType(),type,"I"),regs.getRegisterC(),regs.getRegisterD()));
       if(replacement.equals("drawable") || replacement.startsWith("setImage") || replacement.equals("decodeResource"))drawables++; else strings++;
      }
     }
     impl=mut;
    }
    methods.add(new ImmutableMethod(method.getDefiningClass(),method.getName(),method.getParameters(),method.getReturnType(),
      method.getAccessFlags(),method.getAnnotations(),method.getHiddenApiRestrictions(),impl));
   }
   classes.add(new ImmutableClassDef(cls.getType(),cls.getAccessFlags(),cls.getSuperclass(),cls.getInterfaces(),cls.getSourceFile(),cls.getAnnotations(),cls.getFields(),methods));
  }
  if(dispatch!=(homeSetting?0:1))throw new IOException("Unexpected dispatch count: "+dispatch);
  if(hooks!=1 || strings==0 || drawables==0) throw new IOException("Missing hook: "+hooks+" labels="+strings+" drawables="+drawables);
  helper.getClasses().forEach(classes::add);
  DexFileFactory.writeDexFile(args[2],new ImmutableDexFile(Opcodes.forApi(19),classes));
  System.out.println((homeSetting?"Home editor":"Launcher")+" load hooks="+hooks+", label calls="+strings+", icon calls="+drawables+", dispatch="+dispatch+", added classes="+helper.getClasses().size());
 }
}
