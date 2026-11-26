#!/usr/bin/env python3
"""Read a live SA6400 DTB and renumber existing SATA nodes by physical bay."""
import argparse
import re
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=Path("/run/model.dtb"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--hba-pcie", default="0000:00:03.2,00.0")
    p.add_argument("--ssd-pcie", default="0000:00:11.4")
    p.add_argument("--ssd-port", type=int, default=3)
    args = p.parse_args()
    if args.hba_pcie == args.ssd_pcie:
        raise ValueError("Expected two distinct controllers")
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite: " + str(args.output))

    src = subprocess.check_output(
        ["dtc", "-I", "dtb", "-O", "dts", str(args.input)],
        text=True,
    )
    if 'model = "synology_epyc7002_sa6400";' not in src:
        raise ValueError("This helper is intended for SA6400 / epyc7002")

    mapping = {}
    enclosures = set()
    for disk in sorted(Path("/sys/block").glob("sata*")):
        info = dict(
            line.split("=", 1)
            for line in (disk / "device/syno_block_info").read_text().splitlines()
            if "=" in line
        )
        pci = info["pciepath"]
        port = int(info["ata_port_no"])
        if pci == args.ssd_pcie and port == args.ssd_port:
            slot = 25
        elif pci == args.hba_pcie:
            device = (disk / "device").resolve()
            end = next(x for x in device.parents if x.name.startswith("end_device-"))
            sas = Path("/sys/class/sas_device") / end.name
            bay = int((sas / "bay_identifier").read_text())
            phy = int((sas / "phy_identifier").read_text())
            enclosures.add((sas / "enclosure_identifier").read_text().strip())
            if not 0 <= bay < 24:
                raise ValueError("Bay outside expected 24-bay enclosure")
            slot = bay + 1
            print(f"{disk.name}: Bay={bay}, PHY={phy}")
        else:
            raise ValueError(f"Unexpected controller or port: {disk.name} {pci} {port}")
        if (pci, port) in mapping or slot in mapping.values():
            raise ValueError("Duplicate port or physical slot")
        mapping[(pci, port)] = slot
        print(f"{disk.name}: {pci}, port={port} -> slot {slot}")

    if len(enclosures) != 1 or 25 not in mapping.values():
        raise ValueError("Expected one populated SAS enclosure and one internal SSD")

    pattern = re.compile(
        r"(?ms)^([ \t]+)internal_slot@([0-9a-fA-F]+)"
        r"[ \t]*\{.*?^\1\};[ \t]*$"
    )
    matches = list(pattern.finditer(src))
    if not matches or len(matches) != len(mapping):
        raise ValueError("DTB does not describe all current SATA drives; use auto-generated baseline")
    blocks = []
    seen = set()
    for m in matches:
        block = m.group()
        pci = re.search(r'pcie_root = "([^"]+)"', block).group(1)
        port = int(re.search(r'ata_port = <(0x[0-9a-fA-F]+)>', block).group(1), 16)
        key = (pci, port)
        if key not in mapping or key in seen:
            raise ValueError(f"Unexpected or duplicate DTB port: {key}")
        seen.add(key)
        slot = mapping[key]
        block = re.sub(
            r"internal_slot@[0-9a-fA-F]+", f"internal_slot@{slot}", block, count=1
        )
        blocks.append((slot, block))
    for a, b in zip(matches, matches[1:]):
        if src[a.end():b.start()].strip():
            raise ValueError("Unexpected non-contiguous SATA node blocks")

    blocks.sort()
    out = (
        src[:matches[0].start()]
        + "\n\n".join(block for _, block in blocks)
        + src[matches[-1].end():]
    )
    subprocess.run(
        ["dtc", "-I", "dts", "-O", "dtb", "-o", "/dev/null"],
        input=out, text=True, check=True,
    )
    with args.output.open("x") as f:
        f.write(out)
    print(f"Generated {args.output}; slots: {[slot for slot, _ in blocks]}")
    print("Review the DTS and actual physical mapping before importing into Arc.")


if __name__ == "__main__":
    main()
