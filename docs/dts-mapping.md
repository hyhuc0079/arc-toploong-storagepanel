# DTS 生成与验证 / DTS mapping

适用范围：本次 SA6400 / SAS expander 方案。此指南不要求修改驱动或在线重建设备树。

## 1. 采集实际映射（只读）

在 DSM root 下执行：

```sh
for p in /sys/block/sata*; do
    [ -e "$p" ] || continue
    echo "=== $(basename "$p") ==="
    cat "$p/device/syno_block_info"
    dev=$(readlink -f "$p/device")
    end=$(printf '%s\n' "$dev" | grep -oE 'end_device-[^/]+' | tail -n 1)
    if [ -n "$end" ]; then
        for k in bay_identifier phy_identifier enclosure_identifier; do
            printf '%s=' "$k"
            cat "/sys/class/sas_device/$end/$k"
        done
    fi
done
dtc -I dtb -O dts /run/model.dtb -o /tmp/model-original.dts
```

Use a normally enumerated system as the starting point. Read the live device's pciepath and ata_port_no from syno_block_info, and its physical bay_identifier from the SAS endpoint. Do not assume the ATA port equals the PHY or bay.

## 2. 计算目标节点 / Assign target nodes

| 实测设备 | PCIe path | ata_port_no | Bay / PHY | DTS node |
| --- | --- | --- | --- | --- |
| 板载 S4500 | 0000:00:11.4 | 3 | — | internal_slot@25 |
| 前置第一行第一列 | 0000:00:03.2,00.0 | 0 | 0 / 4 | internal_slot@1 |
| 前置第一行第二列 | 0000:00:03.2,00.0 | 1 | 1 / 5 | internal_slot@2 |

另有实测第一列第二行 Bay 4 / PHY 8（物理位置 5）。其他位置的对应关系尚未全部验证。目标编号为 Bay ID + 1，前提是已确认本背板 Bay ID 与 6×4 物理位置一致。内置 SATA SSD 使用 25。

## 3. 生成自定义 DTS

以步骤 1 导出的完整 /tmp/model-original.dts 为模板。保留 model、version、power_limit、NVMe、USB 及其他原始配置，只根据当前设备匹配 pcie_root 与 ata_port，然后改变对应 internal_slot@N 节点名称。可按目标编号排序；不要求节点连续。

例如第一块红盘：

```dts
internal_slot@1 {
    protocol_type = "sata";
    ahci {
        pcie_root = "0000:00:03.2,00.0";
        ata_port = <0x00>;
        internal_mode;
    };
};
```

不要按 PHY 直接写 ata_port，不要为不存在的设备猜测虚拟端口。空闲盘位由前端的 24 格布局显示，不需要为它们虚构 DTS 节点。新增硬盘前应恢复自动 DTS 或确保新盘也有真实、正确的端口映射，再重新生成完整文件。

可使用仓库中的 [generate_dts.py](../generate_dts.py)（根据本次实机成功的生成逻辑整理，仍需逐台验证）：

```sh
python3 generate_dts.py --output /tmp/SA6400.dts
```

默认 PCIe 路径仅对应本次测试硬件；不同硬件需显式指定 --hba-pcie、--ssd-pcie、--ssd-port，且先验证 Bay ID 的物理含义。脚本要求自动生成的原始 DTB 已包含所有当前 SATA 磁盘的映射，不会猜测缺失节点。它只读取系统信息并输出 DTS，不修改系统配置。

```sh
dtc -I dts -O dtb /tmp/SA6400.dts -o /tmp/SA6400.dtb
```

原始 DSM 节点本身可能产生 unit_address_vs_reg 或 unique_unit_address 警告；不要为消除警告擅自加入 reg。编译成功不是运行兼容性的保证。

## 4. Import and verify

Upload the DTS to /mnt/p3/users/SA6400.dts in Arc Config Mode, rebuild the loader and boot DSM. Verify the runtime tree, Disk IDs, SATA classification and existing storage before applying the frontend patch:

```sh
ls -l /etc/user_model.dts
sha256sum /etc/model.dtb /etc.defaults/model.dtb /run/model.dtb
dtc -I dtb -O dts /run/model.dtb 2>/dev/null | grep -A 8 'internal_slot@'
synodisk --enum -t internal
for p in /sys/block/sata*; do
    [ -e "$p" ] || continue
    synodiskport -portcheck "/dev/$(basename "$p")"
done
cat /proc/mdstat
df -h | grep volume
```

The three DTB checksums matched on the test machine. The successful non-contiguous IDs were 1, 2 and 25. Static DTS cannot guarantee future port assignments; verify on each topology change. Restore the original loader configuration if enumeration or storage is abnormal. Never initialize a missing disk as part of this test.
