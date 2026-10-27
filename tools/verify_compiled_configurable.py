#!/usr/bin/env python3
"""Reconstruct target-compiled home ODEXs and independently verify emitted changes."""
import argparse
from pathlib import Path
import subprocess
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--backup-dir',required=True,type=Path)
p.add_argument('--build-dir',required=True,type=Path)
p.add_argument('--java-home',required=True,type=Path)
p.add_argument('--dexlib-libs',required=True,type=Path)
a=p.parse_args();root=Path(__file__).resolve().parents[1];b=a.build_dir.resolve();fw=a.backup_dir.resolve()/'system/framework'
cp=':'.join(str(p) for p in sorted(a.dexlib_libs.resolve().rglob('*.jar')))
java=a.java_home.resolve()/'bin/java'
def run(source,args,log):
 with (b/log).open('w') as out:
  result=subprocess.run([str(java),'-Xmx2g','-cp',cp,str(source),*map(str,args)],stdout=out,stderr=subprocess.STDOUT)
 if result.returncode: raise RuntimeError('Compiled verification failed: '+str(b/log))
for name in ['Launcher_WP3','HKMC_HomeSetting_WP']:
 dex=b/(name+'-compiled.dex')
 run(root/'examples/configurable/DeodexLauncher.java',[b/(name+'-patched.odex'),fw,dex],name+'-compiled-deodex.log')
 run(root/'tools/VerifyCompiledConfigurableLauncher.java',[b/(name+'-patched.dex'),dex,fw],name+'-compiled-verify.log')
 print(name+': compiled ODEX reconstruction/structural/reflection/Dalvik checks passed')
