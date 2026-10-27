// Reconstruct standard API-19 DEX using the matching firmware class definitions.
// Fail closed on analysis errors, remaining optimized instructions, or changed
// code size (branch/try/debug offsets must still address the original code).
import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.jf.dexlib2.*;
import org.jf.dexlib2.analysis.*;
import org.jf.dexlib2.dexbacked.*;
import org.jf.dexlib2.iface.*;
import org.jf.dexlib2.iface.instruction.*;
import org.jf.dexlib2.immutable.*;
import org.jf.dexlib2.immutable.instruction.*;
import org.jf.dexlib2.iface.instruction.formats.*;

class DeodexLauncher {
    // Only six launcher/editor unresolved-null close calls audited from their
    // source instructions. Each physical input must independently match the
    // receiver, quick-call slot, preceding branch operands, and exact resolved API.
    // Some cleanup branches guard a different register from the null receiver;
    // preserve this OEM behavior exactly instead of correcting its control flow.
    static final Map<String, String> NULL_CLEANUP = Map.ofEntries(
        Map.entry("Lcom/hkmc/system/app/homesetting/b/b;->a@3f", "1,11,Ljava/io/FileReader;,Ljava/io/InputStreamReader;,0,5"),
        Map.entry("Lcom/hkmc/system/app/homesetting/b/b;->a@44", "2,11,Ljava/io/BufferedReader;,Ljava/io/BufferedReader;,0,5"),
        Map.entry("Lcom/android/launcher3/d/d;->e@4f", "0,11,Ljava/io/FileReader;,Ljava/io/InputStreamReader;,0,5"),
        Map.entry("Lcom/android/launcher3/d/d;->e@54", "0,11,Ljava/io/FileReader;,Ljava/io/InputStreamReader;,0,5"),
        Map.entry("Lcom/android/launcher3/view/b/ab;->a@db", "3,13,Landroid/os/ParcelFileDescriptor;,Landroid/os/ParcelFileDescriptor;,1,-203"),
        Map.entry("Lcom/android/launcher3/view/b/ab;->a@194", "3,13,Landroid/os/ParcelFileDescriptor;,Landroid/os/ParcelFileDescriptor;,1,5"));
    public static void main(String[] args) throws Exception {
        var opcodes = Opcodes.forApi(19);
        var input = (DexBackedOdexFile) DexFileFactory.loadDexFile(new File(args[0]), opcodes);
        var folder = Path.of(args[1]);
        List<ClassProvider> providers = new ArrayList<>();
        Set<Path> loaded = new HashSet<>();
        for (String dependency : input.getDependencies()) {
            String name = Path.of(dependency).getFileName().toString().replace(".jar", ".odex");
            Path path = folder.resolve(name);
            if (!Files.exists(path)) throw new IOException("Missing ODEX dependency: " + dependency);
            providers.add(new DexClassProvider(DexFileFactory.loadDexFile(path.toFile(), opcodes)));
            loaded.add(path);
            System.out.println("Dependency: " + path);
        }
        // Required vendor libraries can be outside the ODEX boot dependency list.
        try (var files = Files.list(folder)) {
            for (Path path : files.sorted().toList()) {
                if (!path.toString().endsWith(".odex") || loaded.contains(path)) continue;
                providers.add(new DexClassProvider(DexFileFactory.loadDexFile(path.toFile(), opcodes)));
            }
        }
        providers.add(new DexClassProvider(input));
        ClassPath classPath = new ClassPath(providers, false, ClassPath.NOT_ART);
        var inline = InlineMethodResolver.createInlineMethodResolver(input.getOdexVersion());
        List<ClassDef> classes = new ArrayList<>();
        int methodCount = 0, errors = 0;
        for (ClassDef cls : input.getClasses()) {
            List<Method> methods = new ArrayList<>();
            for (Method method : cls.getMethods()) {
                MethodImplementation impl = method.getImplementation();
                if (impl != null) {
                    try {
                        var analyzer = new MethodAnalyzer(classPath, method, inline, false);
                        if (analyzer.getAnalysisException() != null) throw analyzer.getAnalysisException();
                        var instructions = new ArrayList<Instruction>(analyzer.getInstructions());
                        int address = 0;
                        for (int i = 0; i < instructions.size(); i++) {
                            var instruction = instructions.get(i);
                            if (instructions.get(i) instanceof UnresolvedOdexInstruction unresolved) {
                                var quick = unresolved.originalInstruction;
                                String key = method.getDefiningClass() + "->" + method.getName() + "@" + Integer.toHexString(address);
                                if (NULL_CLEANUP.containsKey(key) && quick.getOpcode() == Opcode.INVOKE_VIRTUAL_QUICK && quick instanceof Instruction35ms q) {
                                    String[] expected = NULL_CLEANUP.get(key).split(",");
                                    int register = Integer.parseInt(expected[0]);
                                    if (unresolved.objectRegisterNum != register || q.getRegisterC() != register ||
                                        q.getRegisterCount() != 1 || q.getVtableIndex() != Integer.parseInt(expected[1]))
                                        throw new IOException("Cleanup operand mismatch: " + key);
                                    if (i == 0 || instructions.get(i-1).getOpcode() != Opcode.IF_EQZ ||
                                        ((OneRegisterInstruction) instructions.get(i-1)).getRegisterA() != Integer.parseInt(expected[4]) ||
                                        ((OffsetInstruction) instructions.get(i-1)).getCodeOffset() !=
                                            Integer.parseInt(expected[5]))
                                        throw new IOException("Cleanup preceding branch differs from audited source: " + key);
                                    var reference = ((ClassProto) classPath.getClass(expected[2])).getMethodByVtableIndex(q.getVtableIndex());
                                    if (!reference.getDefiningClass().equals(expected[3]) ||
                                        !reference.getName().equals("close") || !reference.getReturnType().equals("V") ||
                                        !reference.getParameterTypes().isEmpty()) throw new IOException("Unexpected cleanup: " + reference);
                                    instructions.set(i, new ImmutableInstruction35c(Opcode.INVOKE_VIRTUAL,1,register,0,0,0,0,reference));
                                    System.out.println("Resolved null cleanup " + key + ": " + reference);
                                } else {
                                    System.err.println("Unresolved: " + method + " at 0x" + Integer.toHexString(address) +
                                        " receiver=v" + unresolved.objectRegisterNum +
                                        " vtable=" + (quick instanceof Instruction35ms q ? q.getVtableIndex() : "range"));
                                }
                            }
                            address += instruction.getCodeUnits();
                        }
                        int oldSize = 0, newSize = 0;
                        for (var instruction : impl.getInstructions()) oldSize += instruction.getCodeUnits();
                        for (var instruction : instructions) {
                            if (instruction.getOpcode().odexOnly())
                                throw new IOException("Unresolved optimized opcode: " + instruction.getOpcode());
                            newSize += instruction.getCodeUnits();
                        }
                        if (oldSize != newSize) throw new IOException("Instruction addresses changed");
                        impl = new ImmutableMethodImplementation(impl.getRegisterCount(), instructions,
                            impl.getTryBlocks(), impl.getDebugItems());
                        methodCount++;
                    } catch (Exception e) {
                        System.err.println(method + ": " + e);
                        errors++;
                    }
                }
                methods.add(new ImmutableMethod(method.getDefiningClass(), method.getName(),
                    method.getParameters(), method.getReturnType(), method.getAccessFlags(),
                    method.getAnnotations(), method.getHiddenApiRestrictions(), impl));
            }
            classes.add(new ImmutableClassDef(cls.getType(), cls.getAccessFlags(), cls.getSuperclass(),
                cls.getInterfaces(), cls.getSourceFile(), cls.getAnnotations(), cls.getFields(), methods));
        }
        System.out.println("Classes: " + classes.size() + ", reconstructed methods: " + methodCount + ", errors: " + errors);
        if (errors != 0) throw new IOException("Deodexing incomplete; no output written");
        DexFileFactory.writeDexFile(args[2], new ImmutableDexFile(opcodes, classes));
    }
}
