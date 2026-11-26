#!/usr/bin/env python3
"""TOPLOONG 24+1 StorageManager layout preview v2 (alignment correction). No storage configuration writes."""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

EXPECTED = '678c041572871f0060c6f2da74bfc96f40d8a4c71363d2303345916c38c6edca'
UI = Path('/usr/local/packages/@appstore/StorageManager/ui')
BACKUP = Path('/root/toploong-panel-test-backup')
V1 = '03275278438434b47d41f98e29bf48902194f1367d8c25a417ca4dba66fdd36d'
KEY = 'RACK_25_Bay_1'
MODEL = 'synology_epyc7002_sa6400'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected exactly one anchor: ' + old[:100])
    return text.replace(old, new, 1)

def patch(data):
    if digest(data) != EXPECTED:
        raise RuntimeError('Unexpected original JS hash; no changes made')
    s = data.decode('utf-8')
    profile = ('RACK_25_Bay_1:{containerName:"TOPLOONG-24+1",containerType:"internal",containerOrder:0,'
               'containerImgCls:"container-toploong-24plus1",bayCount:25,slotSection:[{slotClass:"main",'
               'slotLocation:"Main",slotOrder:-1,slotName:"TOPLOONG-main",imgWidth:414,imgHeight:198,'
               'driveDirection:"horizontal",driveShape:"default-shape",major:"row",rowDir:"UD",colDir:"LR",'
               'toploong:true,driveSection:[{top:20,left:30,rowCnt:6,colCnt:4,xGap:6,yGap:6},'
               '{top:88,left:332,rowCnt:1,colCnt:1,xGap:6,yGap:6}]}]},')
    s = replace_once(s, 'RACK_24_Bay:{', profile+'RACK_24_Bay:{')
    s = replace_once(s, 'RACK_24_Bay:["'+MODEL+'",', KEY+':["'+MODEL+'"],RACK_24_Bay:[')
    # Override only the implicit local host lookup, not expansion-unit or explicit passive-host lookups.
    old = 'getHostImgCfg({unique:e="",imgKey:t=""}={}){if(t.length>0)return Ps(t);'
    new = 'getHostImgCfg({unique:e="",imgKey:t=""}={}){if(!e&&!t&&y.methods.D("unique","")==="'+MODEL+'")return Ps("'+KEY+'-M2X1");if(t.length>0)return Ps(t);'
    s = replace_once(s,old,new)
    # Use CSS backgrounds rather than external artwork/CSS assets. Native drives are unchanged.
    old = 'slotBgMain(){let{imgWidth:e,imgHeight:t}=this.cfg;return{width:`${e}px`,height:`${t}px`}}'
    new = ('slotBgMain(){let{imgWidth:e,imgHeight:t}=this.cfg;let s={width:`${e}px`,height:`${t}px`};'
           'if(this.cfg.toploong)Object.assign(s,{position:"relative",backgroundImage:'
           '"linear-gradient(#202a34,#202a34),linear-gradient(#202a34,#202a34),linear-gradient(#aab6c4,#8795a5)",'
           'backgroundSize:"282px 168px,84px 54px,302px 188px",backgroundPosition:"16px 10px,320px 70px,6px 0",'
           'backgroundRepeat:"no-repeat"});return s}')
    s = replace_once(s,old,new)
    old = 's("div",{class:e.machineBgCls,style:e.styleObj},[e.isMainSlotSection?'
    new = ('s("div",{class:e.machineBgCls,style:e.styleObj},[e.cfg.toploong?'
           's("div",{style:{position:"absolute",top:"49px",left:"317px",width:"90px",textAlign:"center",'
           'fontSize:"12px",color:"inherit",pointerEvents:"none"}},[e._v("Internal SSD")]):e._e(),e.isMainSlotSection?')
    s = replace_once(s,old,new)
    return s.encode('utf-8')

def atomic_write(path, data):
    st = path.stat()
    fd, name = tempfile.mkstemp(prefix='.toploong-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(name,st.st_mode & 0o7777)
        os.chown(name,st.st_uid,st.st_gid)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def apply(ui, backup):
    js=ui/'storage_panel.js'; gz=ui/'storage_panel.js.gz'
    live=js.read_bytes(); zipped=gz.read_bytes()
    if gzip.decompress(zipped)!=live:
        raise RuntimeError('Live JS and gzip do not match; no changes made')
    if not backup.exists():
        if digest(live)!=EXPECTED:
            raise RuntimeError('Original backup missing; refusing to overwrite')
        backup.mkdir(mode=0o700)
        for p in (js,gz): shutil.copy2(p,backup/p.name)
    source=(backup/js.name).read_bytes()
    original_gz=(backup/gz.name).read_bytes()
    if digest(source)!=EXPECTED or gzip.decompress(original_gz)!=source:
        raise RuntimeError('Original backup validation failed')
    out=patch(source); new_hash=digest(out)
    if digest(live) not in (EXPECTED,V1,new_hash):
        raise RuntimeError('Unknown live version; refusing to overwrite')
    meta=backup/'patched.sha256'
    old_meta=meta.read_bytes() if meta.exists() else None
    try:
        atomic_write(js,out); atomic_write(gz,gzip.compress(out,mtime=0))
        if gzip.decompress(gz.read_bytes())!=js.read_bytes() or js.read_bytes()!=out:
            raise RuntimeError('Post-install verification failed')
        if meta.exists(): atomic_write(meta,(new_hash+'\n').encode())
        else: meta.write_text(new_hash+'\n')
    except BaseException:
        atomic_write(js,live); atomic_write(gz,zipped)
        if old_meta is not None: meta.write_bytes(old_meta)
        elif meta.exists(): meta.unlink()
        raise
    print('APPLY V2 OK:',KEY, 'SHA256:',new_hash, 'Original backup preserved:',backup)

def restore(ui,backup):
    js=ui/'storage_panel.js'; gz=ui/'storage_panel.js.gz'
    source=(backup/js.name).read_bytes(); zipped=(backup/gz.name).read_bytes()
    if digest(source)!=EXPECTED or gzip.decompress(zipped)!=source:
        raise RuntimeError('Original backup validation failed')
    allowed=(EXPECTED,V1,digest(patch(source)))
    live=js.read_bytes(); live_gz=gz.read_bytes()
    if digest(live) not in allowed or digest(gzip.decompress(live_gz)) not in allowed:
        raise RuntimeError('Unknown live version; refusing to overwrite')
    try:
        atomic_write(js,source); atomic_write(gz,zipped)
    except BaseException:
        atomic_write(js,live); atomic_write(gz,live_gz); raise
    print('RESTORE OK:',digest(js.read_bytes()))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['apply','restore','build'])
    p.add_argument('--ui',type=Path,default=UI); p.add_argument('--backup',type=Path,default=BACKUP)
    p.add_argument('--input',type=Path); p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.action=='build':
        if not a.input or not a.output: p.error('build requires --input and --output')
        a.output.write_bytes(patch(a.input.read_bytes()))
        print('BUILD OK',digest(a.output.read_bytes()))
    elif a.action=='apply': apply(a.ui,a.backup)
    else: restore(a.ui,a.backup)
