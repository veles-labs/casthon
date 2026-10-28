pub struct TemplateFile {
    pub path: &'static str,
    pub contents: &'static [u8],
}

pub const FLIPPER: &[TemplateFile] = &[
    TemplateFile {
        path: ".gitignore",
        contents: include_bytes!("../templates/flipper/.gitignore"),
    },
    TemplateFile {
        path: "README.md",
        contents: include_bytes!("../templates/flipper/README.md"),
    },
    TemplateFile {
        path: "pyproject.toml",
        contents: include_bytes!("../templates/flipper/pyproject.toml"),
    },
    TemplateFile {
        path: "contracts/__init__.py",
        contents: include_bytes!("../templates/flipper/contracts/__init__.py"),
    },
    TemplateFile {
        path: "contracts/flipper.py",
        contents: include_bytes!("../templates/flipper/contracts/flipper.py"),
    },
    TemplateFile {
        path: "tests/test_flipper.py",
        contents: include_bytes!("../templates/flipper/tests/test_flipper.py"),
    },
    TemplateFile {
        path: "tests/live/test_flipper.py",
        contents: include_bytes!("../templates/flipper/tests/live/test_flipper.py"),
    },
];
