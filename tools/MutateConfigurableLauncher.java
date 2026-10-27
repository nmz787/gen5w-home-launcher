// Negative-test fixtures only. Never writes the input DEX.
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

class MutateConfigurableLauncher {
 static final String HELPER="Lcom/android/launcher3/configurable/TileRegistry;";
 static final String CLICK="Lcom/android/launcher3/view/bp;";
 public static void main(String[] args)throws Exception {
  if(args.length!=3)throw new IllegalArgumentException("input.dex output.dex mode");
  if(new File(args[0]).getCanonicalFile().equals(new File(args[1]).getCanonicalFile()))throw new IllegalArgumentException("Input must remain untouched");
  String mode=args[2];
  var dex=DexFileFactory.loadDexFile(new File(args[0]),Opcodes.forApi(19));
  var classes=new ArrayList<ClassDef>();int mutations=0;
  for(var cls:dex.getClasses()) {
   var methods=new ArrayList<Method>();
   for(var method:cls.getMethods()) {
    MethodImplementation impl=method.getImplementation();
    if(impl!=null&&mutations==0) {
     var mut=new MutableMethodImplementation(impl);boolean change=false;
     boolean helper=cls.getType().startsWith("Lcom/android/launcher3/configurable/");
     if(mode.equals("oem-instruction")&&!helper&&!mut.getInstructions().isEmpty()) {
      mut.addInstruction(0,new BuilderInstruction10x(Opcode.NOP));change=true;
     }else if(mode.equals("helper-instruction")&&helper&&!mut.getInstructions().isEmpty()) {
      mut.addInstruction(0,new BuilderInstruction10x(Opcode.NOP));change=true;
     }else if(mode.equals("editor-click")&&!helper&&impl.getRegisterCount()>0) {
      var ref=new ImmutableMethodReference(HELPER,"launch",List.of("Landroid/content/Intent;"),"V");
      mut.addInstruction(0,new BuilderInstruction35c(Opcode.INVOKE_STATIC,1,0,0,0,0,0,ref));change=true;
     }else if((mode.equals("missing-click")||mode.equals("wrong-click-register"))&&cls.getType().equals(CLICK)&&method.getName().equals("onClick")) {
      for(int i=0;i<mut.getInstructions().size();i++) {
       var ins=mut.getInstructions().get(i);
       if(ins instanceof ReferenceInstruction ri&&ri.getReference() instanceof MethodReference ref&&ref.getDefiningClass().equals(HELPER)&&ref.getName().equals("launch")) {
        var regs=(FiveRegisterInstruction)ins;
        if(mode.equals("missing-click")) {
         var original=new ImmutableMethodReference("Lcom/android/launcher3/utils/a;","b",List.of("Landroid/content/Intent;"),"V");
         mut.replaceInstruction(i,new BuilderInstruction35c(Opcode.INVOKE_STATIC,1,regs.getRegisterC(),0,0,0,0,original));
        }else {
         int replacement=(regs.getRegisterC()+1)%Math.min(impl.getRegisterCount(),16);
         if(replacement==regs.getRegisterC())throw new AssertionError("No alternative dispatch register");
         mut.replaceInstruction(i,new BuilderInstruction35c(Opcode.INVOKE_STATIC,1,replacement,0,0,0,0,ref));
        }
        change=true;break;
       }
      }
     }
     if(change){impl=mut;mutations++;System.out.println(mode+": "+method);}
    }
    methods.add(new ImmutableMethod(method.getDefiningClass(),method.getName(),method.getParameters(),method.getReturnType(),method.getAccessFlags(),method.getAnnotations(),method.getHiddenApiRestrictions(),impl));
   }
   int flags=cls.getAccessFlags();
   if(mode.equals("helper-flags")&&mutations==0&&cls.getType().startsWith("Lcom/android/launcher3/configurable/")) {
    flags^=0x10000;mutations++;System.out.println(mode+": "+cls.getType());
   }
   classes.add(new ImmutableClassDef(cls.getType(),flags,cls.getSuperclass(),cls.getInterfaces(),cls.getSourceFile(),cls.getAnnotations(),cls.getFields(),methods));
  }
  if(mutations!=1)throw new AssertionError("Expected exactly one mutation; got "+mutations);
  DexFileFactory.writeDexFile(args[1],new ImmutableDexFile(Opcodes.forApi(19),classes));
 }
}
