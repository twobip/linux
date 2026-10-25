#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the T6040 wire builders and calibration checks without a GPU."""

from pathlib import Path
import re
import subprocess
import tempfile

DRIVER = Path(__file__).resolve().parents[2] / "drivers/gpu/drm/asahi"


def omit_item(source, signature):
    """Omit only the OF adapter; the validation and encoders are compiled verbatim."""
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[:start] + source[end:]


HEADER = r'''
#![allow(dead_code)]
mod prelude {
    pub use std::mem::size_of;
    pub type Result<T = ()> = std::result::Result<T, Error>;
    #[derive(Debug)]
    pub struct Error;
    impl From<std::num::TryFromIntError> for Error {
        fn from(_: std::num::TryFromIntError) -> Self { Self }
    }
    pub const EINVAL: Error = Error;
    pub const EOVERFLOW: Error = Error;
    pub unsafe trait Zeroable {}
}
macro_rules! static_assert { ($e:expr) => { const _: () = assert!($e); } }
fn clear<T>(value: &mut T) {
    unsafe { std::ptr::write_bytes(value, 0, 1); }
}
mod float;
mod initdata;
mod g17 {
    pub mod fw { pub(crate) use crate::initdata; }
    mod calibration;
}
'''

TEST = r'''
#[test]
fn power_configuration_uses_only_its_inputs() {
    use initdata::v25g83::PowerConfig25G83;
    let mut first = PowerConfig25G83([0xcc; 0x6510]);
    let mut leakage = [0; 56];
    leakage[0] = 0x44480000;
    leakage[1] = 0x44800000;
    leakage[32] = 0x43000000;
    leakage[33] = 0x43000000;
    leakage[52] = 0x43800000;
    leakage[54] = 0x44000000;
    first.init(0x12340000, 0x56780000, 0xabcdef, 76543, &leakage);
    let word = |bytes: &[u8], off| u32::from_le_bytes(bytes[off..off + 4].try_into().unwrap());
    for off in [0xa04, 0xabc, 0x28c8, 0x28cc, 0x28d0, 0x2a08] {
        assert_eq!(word(&first.0, off), 76543);
    }
    for off in [0x9e0, 0x2a04] {
        assert_eq!(word(&first.0, off), (76543f32).to_bits());
    }
    for (i, value) in leakage.iter().enumerate() {
        assert_eq!(word(&first.0, 0x642c + 4 * i), *value);
    }
    assert_eq!(u64::from_le_bytes(first.0[0x3b50..0x3b58].try_into().unwrap()), 0x12340080);
    assert_eq!(u64::from_le_bytes(first.0[0x6318..0x6320].try_into().unwrap()), 0x56780000);
    assert_eq!(word(&first.0, 0x63d4), 0xabcdef);
    let mut second = PowerConfig25G83([0; 0x6510]);
    second.init(0x12340000, 0x56780000, 0xabcdef, 76543, &leakage);
    assert_eq!(first.0, second.0);
    second.init(0x12340000, 0x56780000, 0xabcdef, 80000, &[0; 56]);
    assert_eq!(word(&second.0, 0xa04), 80000);
    assert_eq!(word(&second.0, 0x9e0), (80000f32).to_bits());
    for i in 0..56 {
        assert_eq!(word(&second.0, 0x642c + 4 * i), 0);
    }
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix="asahi-t6040-") as tmp:
        root = Path(tmp)
        (root / "initdata").mkdir()
        (root / "g17").mkdir()
        for source, target in [
            ("g17/fw/initdata.rs", "initdata.rs"),
            ("g17/fw/initdata/v25g83.rs", "initdata/v25g83.rs"),
        ]:
            text = (DRIVER / source).read_text()
            (root / target).write_text(text.replace("use kernel::prelude::*;", "use crate::prelude::*;"))
        text = (DRIVER / "float.rs").read_text().split("impl<'a> TryFrom<of::Property")[0]
        text = re.sub(r"use kernel::\{.*?\};", "use crate::prelude::*;", text, flags=re.S)
        (root / "float.rs").write_text(text)
        text = (DRIVER / "g17/calibration.rs").read_text()
        text = omit_item(text, "fn words<const N:")
        text = omit_item(text, "    pub(super) fn read(")
        text = re.sub(r"use crate::driver::AsahiDrmDevice;", "", text)
        text = re.sub(r"use kernel::\{.*?\};", "use crate::prelude::*;", text)
        text = text.replace("#[kunit_tests(asahi_t6040_calibration)]", "#[cfg(test)]")
        (root / "g17/calibration.rs").write_text(text)
        (root / "main.rs").write_text(HEADER + TEST)
        binary = root / "test"
        subprocess.run(["rustc", "--edition=2021", "--test", "-Dwarnings",
                        str(root / "main.rs"), "-o", str(binary)], check=True)
        subprocess.run([str(binary), "--test-threads=1"], check=True)


if __name__ == "__main__":
    main()
