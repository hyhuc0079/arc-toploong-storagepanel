# Integration V2 — 安装、验证与回滚 / Installation, validation and rollback

## 适用条件 / Prerequisites

本指南对应 2026-11-27 实机验收的原始脚本，未改写安装逻辑。Arc 4.2.11 / SA6400 DSM 7.4.1-90080 / StorageManager 1.1.0-2018。请备份重要数据、引导盘及 Arc 配置。不要在存储池重建或恢复时安装。

The installer is not portable as-is. The physical mapping checks are hardcoded for the tested X99 CH8 system: HBA PCI path 0000:00:03.2,00.0, onboard SATA path 0000:00:11.4 port 3, and the specific SAS enclosure identifier embedded in the installer. Inspect your own sysfs attributes using the [mapping guide](dts-mapping.md). A different topology needs a reviewed, rebuilt payload, not a bypass of the guard. At boot the disks addon can fall back to stock numbering; verify logs. The panel profile is limited to SA6400 + 1X1 M.2 and the exact tested JavaScript input hash.

Download both shell files into /mnt/p3/users/ in Arc Config Mode, and verify checksums against [SHA256SUMS](../SHA256SUMS). Do not run them in DSM.

## 1. 前置 V1 / V1 prerequisite

If Dynamic Disks V1 is already installed, skip this section. V2 checks the exact V1 disks.sh hash and will not accept stock Arc directly.

V1 requires the exact original disks addon and the tested static DTS (SHA-256 abd962b90565895051bd7fef2a752b97885d318cf53422b0c5b23f77beabd6c7). [examples/SA6400.dts](../examples/SA6400.dts) is specific to the original tested topology, not a universal starting tree. The original static procedure is in the [legacy guide](legacy-static-zh.md). Do not blindly boot the example on a different machine.

Arc may automatically rename an uploaded DTS to model.dts. If that is the exact verified DTS and no SA6400.dts exists, rename it after checking:

```sh
(
set -e
cd /mnt/p3/users
echo 'abd962b90565895051bd7fef2a752b97885d318cf53422b0c5b23f77beabd6c7  model.dts' | sha256sum -c -
test ! -e SA6400.dts
mv model.dts SA6400.dts
)
```

```sh
cd /mnt/p3/users
sh toploong_dynamic_install.sh check
# Continue only if CHECK OK; stop on any mismatch.
sh toploong_dynamic_install.sh apply
```

V1 backs up the original archive and static DTS under /mnt/p3/toploong-dynamic-backup-v1/ and removes the active static file. The tested procedure rebuilt and booted V1 before proceeding to V2. Verify cold-boot mappings and existing storage at that stage. V1 hotplug may require a delayed manual update; V2 resolves the observed timing problem.

## 2. 安装 Integration V2 / Install V2

Return to Arc Config Mode. Ensure neither /mnt/p3/users/SA6400.dts nor /mnt/p3/users/model.dts remains. Do not delete an unknown DTS; inspect/back up first. The installer expects exactly one disks/all.tgz and storagepanel/all.tgz and validates the source and payload hashes.

```sh
cd /mnt/p3/users
sh toploong_integration_v2.sh check
# Expected: CHECK OK: both archive sources and staged V2 payload verified.
sh toploong_integration_v2.sh apply
```

The apply action saves both prior addon archives under /mnt/p3/toploong-integration-backup-v2/. On success return to Arc menu (exit if in a menu-launched shell), select Build Loader, then Boot DSM. Do not select Update Loader; it may replace the patched addons. No further static DTS editing is required.

## 3. 面板入口 / Enable the panel option

On the tested first deployment the frontend service was installed but not enabled automatically. This is a known installation step for the unchanged release script. In DSM as root:

```sh
systemctl daemon-reload
systemctl enable toploong-control-panel.service
systemctl start toploong-control-panel.service
journalctl -b -u toploong-control-panel.service --no-pager
nginx -s reload
```

The service is oneshot: inactive (dead) after a successful execution is normal. Expect TOPLOONG Arc Control option installed. If anchors do not match, stop; do not forcibly patch another JS version.

Close Arc Control and hard-refresh the browser (Ctrl+F5, or a private window). Open Arc Control, click the HDD BAY dropdown, select TOPLOONG_24_Bay and M.2 1X1, then Apply.

```sh
cat /usr/arc/storagepanel.conf
# Expected: TOPLOONG_24_Bay-1X1
```

If the UI entry is unavailable but the backend is installed, test the backend directly:

```sh
/usr/bin/storagepanel.sh TOPLOONG_24_Bay 1X1 && nginx -s reload
```

Verify Storage Manager shows 6×4 front bays, Disk 25 and the native M.2 area. Reboot normally and verify the config, panel and dropdown persist. Do not run the older standalone panel patch on top of the integrated version.

## 4. 验证 / Validation

Before and after boot/hotplug, inspect:

```sh
synodisk --enum -t internal
cat /proc/mdstat
df -h | grep volume
dtc -I dtb -O dts /run/model.dtb 2>/dev/null | grep -A 8 'internal_slot@'
grep 'TOPLOONG:' /var/log/messages | tail -n 40
cat /usr/arc/storagepanel.conf
systemctl is-enabled toploong-control-panel.service
```

Test with a known noncritical disk in an empty physical bay, after normal boot. Do not manually issue update or trigger events during the acceptance test. Allow the bounded readiness retry, DTB generation and delayed compatibility refresh to complete. Verify the actual device identity, physical slot and compatibility status. Example for a newly enumerated /dev/sata5 (substitute the actual device):

```sh
synodiskport -portcheck /dev/sata5
udevadm info --query=property --name=/dev/sata5 | grep SYNO_DEV_DISKPORTTYPE
journalctl -b -u toploong-hdddb-refresh.timer -u toploong-hdddb-refresh.service --no-pager
systemctl status hdddb.service --no-pager -l
tail -n 60 /var/log/hdddb.log
```

Expect SATA, the physical bay + 1 Disk ID and no unexpected changes to existing arrays. The compatibility timer is only queued when hdddb.service is active. If a disk remains unverified, diagnose the timer and hdddb logs; after udev settles, manually restarting hdddb.service is a validated fallback, not evidence of automatic acceptance.

## 5. 故障处理 / Troubleshooting

- Hash mismatch: stop and retain backups. Do not change expected hashes just to install.
- Kernel sees new disk but DSM shows UNKNOWN: check sysfs readiness, TOPLOONG logs and actual DTB. Live mapping changes to existing nodes are intentionally refused. Reboot normally only after ensuring storage is safe.
- DTB correct but udev type UNKNOWN: the original V1 manual recovery used a targeted udev add event after the device tree was updated. This can trigger DSM disk handling; use only for the verified new device, never a global trigger. V2 aims to avoid this recovery.
- UI option absent: check systemctl status, journalctl and python3 /usr/bin/toploong-control-panel.py check. Verify browser cache before changing code.
- An old disk appears: do not initialize or format it to resolve mapping or compatibility. Migration remains a separate DSM task.

## 6. 回滚 / Rollback

To revert to the previous tested V1 disks addon and stock StoragePanel addon, first in DSM as root restore the stock panel and Arc Control resources, and disable the new service/timer. Stop on any failure rather than overwriting mismatched versions:

```sh
/usr/bin/storagepanel.sh RACK_24_Bay 1X1
python3 /usr/bin/toploong-control-panel.py restore
systemctl stop toploong-hdddb-refresh.timer
systemctl disable toploong-control-panel.service
nginx -s reload
```

Then in Arc Config Mode:

```sh
cd /mnt/p3/users
sh toploong_integration_v2.sh restore
```

The installer checks the saved and installed archive hashes and restores both archives. Build Loader, boot DSM, and verify storage. V1 remains installed; V1's earlier restore action is a separate rollback and restores the original static DTS, which may no longer cover added disks. Do not blindly use the old static tree with a changed topology. Prefer restoring a verified loader image/configuration that describes the current disks. Never initialize or format a missing disk.

## 7. 版本与验收 / Release scope

The original V2 installer is retained byte-for-byte. Known first-install service enablement is documented rather than silently changing the hardware-tested code. The final acceptance was confirmed by the maintainer on the test machine. This does not imply universal hardware support, safe live relocation, or that each of 24 bays was individually verified.
