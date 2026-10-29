use anyhow::{Context, Result, bail};
use std::{collections::HashMap, env, fs};
use wasm_encoder::{
    Instruction, Module, ValType,
    reencode::{self, Reencode},
};
use wasmparser::{Operator, Parser, Payload, Validator, WasmFeatures};

struct Lower {
    helpers: HashMap<String, u32>,
    replaced: usize,
}

impl Lower {
    fn call(&mut self, name: &str) -> Result<Instruction<'static>, reencode::Error<String>> {
        let index = self
            .helpers
            .get(name)
            .ok_or_else(|| reencode::Error::UserError(format!("Missing helper {name}")))?;
        self.replaced += 1;
        Ok(Instruction::Call(*index))
    }
}

impl Reencode for Lower {
    type Error = String;

    fn val_type(&mut self, ty: wasmparser::ValType) -> Result<ValType, reencode::Error<String>> {
        match ty {
            wasmparser::ValType::F32 => Ok(ValType::I32),
            wasmparser::ValType::F64 => Ok(ValType::I64),
            _ => reencode::utils::val_type(self, ty),
        }
    }

    // The default implementation bypasses the val_type override.
    fn val_types(
        &mut self,
        types: Vec<wasmparser::ValType>,
    ) -> Result<Vec<ValType>, reencode::Error<String>> {
        types.into_iter().map(|ty| self.val_type(ty)).collect()
    }

    fn parse_export(
        &mut self,
        section: &mut wasm_encoder::ExportSection,
        export: wasmparser::Export<'_>,
    ) -> Result<(), reencode::Error<String>> {
        // The Casper adapter calls constructors directly. Drop the Emscripten
        // startup export along with internal continuation/SoftFloat exports;
        // this leaves the constructor function and internal calls intact.
        let asyncify_control = matches!(
            export.name,
            "asyncify_start_unwind"
                | "asyncify_stop_unwind"
                | "asyncify_start_rewind"
                | "asyncify_stop_rewind"
                | "asyncify_get_state"
        );
        if export.name != "_initialize" && !export.name.starts_with("__sf_") && !asyncify_control {
            reencode::utils::parse_export(self, section, export)?;
        }
        Ok(())
    }

    fn parse_custom_section(
        &mut self,
        module: &mut Module,
        section: wasmparser::CustomSectionReader<'_>,
    ) -> Result<(), reencode::Error<String>> {
        if env::var_os("CSPR_WASM_DEBUG").is_some() && section.name() == "name" {
            reencode::utils::parse_custom_section(self, module, section)?;
        }
        // Drop debug/producers/target_features metadata from the deployment artifact.
        Ok(())
    }

    fn instruction<'a>(
        &mut self,
        op: Operator<'a>,
    ) -> Result<Instruction<'a>, reencode::Error<String>> {
        Ok(match op {
            Operator::F32Const { value } => Instruction::I32Const(value.bits() as i32),
            Operator::F64Const { value } => Instruction::I64Const(value.bits() as i64),
            Operator::F32Load { memarg } => Instruction::I32Load(self.mem_arg(memarg)?),
            Operator::F64Load { memarg } => Instruction::I64Load(self.mem_arg(memarg)?),
            Operator::F32Store { memarg } => Instruction::I32Store(self.mem_arg(memarg)?),
            Operator::F64Store { memarg } => Instruction::I64Store(self.mem_arg(memarg)?),
            Operator::I32ReinterpretF32
            | Operator::F32ReinterpretI32
            | Operator::I64ReinterpretF64
            | Operator::F64ReinterpretI64 => Instruction::Nop,
            Operator::F32Abs => self.call("__sf_f32_abs")?,
            Operator::F32Neg => self.call("__sf_f32_neg")?,
            Operator::F32Ceil => self.call("__sf_f32_ceil")?,
            Operator::F32Floor => self.call("__sf_f32_floor")?,
            Operator::F32Trunc => self.call("__sf_f32_trunc")?,
            Operator::F32Nearest => self.call("__sf_f32_nearest")?,
            Operator::F32Sqrt => self.call("__sf_f32_sqrt")?,
            Operator::F32Add => self.call("__sf_f32_add")?,
            Operator::F32Sub => self.call("__sf_f32_sub")?,
            Operator::F32Mul => self.call("__sf_f32_mul")?,
            Operator::F32Div => self.call("__sf_f32_div")?,
            Operator::F32Min => self.call("__sf_f32_min")?,
            Operator::F32Max => self.call("__sf_f32_max")?,
            Operator::F32Copysign => self.call("__sf_f32_copysign")?,
            Operator::F32Eq => self.call("__sf_f32_eq")?,
            Operator::F32Ne => self.call("__sf_f32_ne")?,
            Operator::F32Lt => self.call("__sf_f32_lt")?,
            Operator::F32Gt => self.call("__sf_f32_gt")?,
            Operator::F32Le => self.call("__sf_f32_le")?,
            Operator::F32Ge => self.call("__sf_f32_ge")?,
            Operator::F64Abs => self.call("__sf_f64_abs")?,
            Operator::F64Neg => self.call("__sf_f64_neg")?,
            Operator::F64Ceil => self.call("__sf_f64_ceil")?,
            Operator::F64Floor => self.call("__sf_f64_floor")?,
            Operator::F64Trunc => self.call("__sf_f64_trunc")?,
            Operator::F64Nearest => self.call("__sf_f64_nearest")?,
            Operator::F64Sqrt => self.call("__sf_f64_sqrt")?,
            Operator::F64Add => self.call("__sf_f64_add")?,
            Operator::F64Sub => self.call("__sf_f64_sub")?,
            Operator::F64Mul => self.call("__sf_f64_mul")?,
            Operator::F64Div => self.call("__sf_f64_div")?,
            Operator::F64Min => self.call("__sf_f64_min")?,
            Operator::F64Max => self.call("__sf_f64_max")?,
            Operator::F64Copysign => self.call("__sf_f64_copysign")?,
            Operator::F64Eq => self.call("__sf_f64_eq")?,
            Operator::F64Ne => self.call("__sf_f64_ne")?,
            Operator::F64Lt => self.call("__sf_f64_lt")?,
            Operator::F64Gt => self.call("__sf_f64_gt")?,
            Operator::F64Le => self.call("__sf_f64_le")?,
            Operator::F64Ge => self.call("__sf_f64_ge")?,
            Operator::I32TruncF32S => self.call("__sf_i32_trunc_f32_s")?,
            Operator::F32ConvertI32S => self.call("__sf_f32_convert_i32_s")?,
            Operator::I32TruncF32U => self.call("__sf_i32_trunc_f32_u")?,
            Operator::F32ConvertI32U => self.call("__sf_f32_convert_i32_u")?,
            Operator::I32TruncF64S => self.call("__sf_i32_trunc_f64_s")?,
            Operator::F64ConvertI32S => self.call("__sf_f64_convert_i32_s")?,
            Operator::I32TruncF64U => self.call("__sf_i32_trunc_f64_u")?,
            Operator::F64ConvertI32U => self.call("__sf_f64_convert_i32_u")?,
            Operator::I64TruncF32S => self.call("__sf_i64_trunc_f32_s")?,
            Operator::F32ConvertI64S => self.call("__sf_f32_convert_i64_s")?,
            Operator::I64TruncF32U => self.call("__sf_i64_trunc_f32_u")?,
            Operator::F32ConvertI64U => self.call("__sf_f32_convert_i64_u")?,
            Operator::I64TruncF64S => self.call("__sf_i64_trunc_f64_s")?,
            Operator::F64ConvertI64S => self.call("__sf_f64_convert_i64_s")?,
            Operator::I64TruncF64U => self.call("__sf_i64_trunc_f64_u")?,
            Operator::F64ConvertI64U => self.call("__sf_f64_convert_i64_u")?,
            Operator::F32DemoteF64 => self.call("__sf_f32_demote_f64")?,
            Operator::I32TruncSatF32S => self.call("__sf_i32_trunc_sat_f32_s")?,
            Operator::I32TruncSatF32U => self.call("__sf_i32_trunc_sat_f32_u")?,
            Operator::I32TruncSatF64S => self.call("__sf_i32_trunc_sat_f64_s")?,
            Operator::I32TruncSatF64U => self.call("__sf_i32_trunc_sat_f64_u")?,
            Operator::I64TruncSatF32S => self.call("__sf_i64_trunc_sat_f32_s")?,
            Operator::I64TruncSatF32U => self.call("__sf_i64_trunc_sat_f32_u")?,
            Operator::I64TruncSatF64S => self.call("__sf_i64_trunc_sat_f64_s")?,
            Operator::I64TruncSatF64U => self.call("__sf_i64_trunc_sat_f64_u")?,
            Operator::F64PromoteF32 => self.call("__sf_f64_promote_f32")?,
            _ => reencode::utils::instruction(self, op)?,
        })
    }
}

pub fn validate(bytes: &[u8]) -> Result<()> {
    // The V1 engine expects MVP Wasm with mutable globals. No floats or newer
    // proposal instructions are accepted in this artifact.
    let features = WasmFeatures::WASM1.difference(WasmFeatures::FLOATS);
    Validator::new_with_features(features)
        .validate_all(bytes)
        .context("Artifact is not float-free MVP Wasm")?;
    for section in Parser::new(0).parse_all(bytes) {
        match section? {
            Payload::StartSection { .. } => bail!("Casper does not support a Wasm start section"),
            Payload::ImportSection(imports) => {
                for import in imports.into_imports() {
                    let import = import?;
                    if import.module != "env" || !import.name.starts_with("casper_") {
                        bail!("Unexpected host import {}::{}", import.module, import.name);
                    }
                }
            }
            Payload::MemorySection(memories) => {
                for memory in memories {
                    let memory = memory?;
                    if memory.initial > 64 || memory.maximum.is_none_or(|n| n > 64) {
                        bail!("Memory exceeds Casper's 64-page limit");
                    }
                }
            }
            _ => {}
        }
    }
    Ok(())
}

pub struct Inspection {
    pub exports: Vec<String>,
    pub imports: Vec<String>,
    pub memory: Vec<(u64, Option<u64>)>,
}

pub fn inspect(bytes: &[u8]) -> Result<Inspection> {
    Validator::new()
        .validate_all(bytes)
        .context("Invalid input Wasm")?;
    let mut result = Inspection {
        exports: vec![],
        imports: vec![],
        memory: vec![],
    };
    for section in Parser::new(0).parse_all(bytes) {
        match section? {
            Payload::ExportSection(exports) => {
                for export in exports {
                    let export = export?;
                    if export.kind == wasmparser::ExternalKind::Func {
                        result.exports.push(export.name.to_owned());
                    }
                }
            }
            Payload::ImportSection(imports) => {
                for import in imports.into_imports() {
                    let import = import?;
                    result
                        .imports
                        .push(format!("{}::{}", import.module, import.name));
                }
            }
            Payload::MemorySection(memories) => {
                for memory in memories {
                    let memory = memory?;
                    result.memory.push((memory.initial, memory.maximum));
                }
            }
            _ => {}
        }
    }
    Ok(result)
}

pub fn run_tool(arguments: Vec<String>) -> Result<()> {
    let args: Vec<_> = std::iter::once("wasm-softfloat".to_owned())
        .chain(arguments)
        .collect();
    if args.len() == 4 && args[1] == "--instrument" {
        let bytes = fs::read(&args[2])?;
        let module = casper_wasm::deserialize_buffer::<casper_wasm::elements::Module>(&bytes)?;
        let imported = module.import_count(casper_wasm::elements::ImportCountType::Function) as u32;
        let module = casper_wasm_utils::inject_gas_counter(
            module,
            &casper_wasm_utils::rules::Set::default(),
            "env",
        )
        .map_err(|_| anyhow::anyhow!("Gas instrumentation failed"))?;
        let mut module = casper_wasm_utils::stack_height::inject_limiter(module, 500)
            .map_err(|_| anyhow::anyhow!("Stack instrumentation failed"))?;
        if env::var_os("CSPR_WASM_DEBUG").is_some() {
            // inject_gas_counter relocates calls but leaves raw name metadata
            // untouched. Keep debug names aligned with the inserted gas import.
            module = module
                .parse_names()
                .map_err(|_| anyhow::anyhow!("Invalid name metadata"))?;
            if let Some(names) = module.names_section_mut() {
                if let Some(functions) = names.functions_mut() {
                    let old = std::mem::take(functions.names_mut());
                    for (index, name) in old {
                        functions
                            .names_mut()
                            .insert(if index >= imported { index + 1 } else { index }, name);
                    }
                }
                if let Some(locals) = names.locals_mut() {
                    let old = std::mem::take(locals.local_names_mut());
                    for (index, names) in old {
                        locals
                            .local_names_mut()
                            .insert(if index >= imported { index + 1 } else { index }, names);
                    }
                }
            }
        }
        fs::write(&args[3], casper_wasm::serialize(module)?)?;
        println!("Instrumented with Casper's 500-slot stack limiter");
        return Ok(());
    }
    if args.len() == 3 && args[1] == "--check" {
        validate(&fs::read(&args[2])?)?;
        println!("Validated float-free Casper V1 Wasm");
        return Ok(());
    }
    if args.len() != 3 {
        bail!("Usage: wasm-softfloat INPUT.wasm OUTPUT.wasm | --check FILE.wasm");
    }
    let bytes = fs::read(&args[1])?;
    Validator::new()
        .validate_all(&bytes)
        .context("Invalid input Wasm")?;
    let mut helpers = HashMap::new();
    for section in Parser::new(0).parse_all(&bytes) {
        if let Payload::ExportSection(exports) = section? {
            for export in exports {
                let export = export?;
                if export.name.starts_with("__sf_") {
                    helpers.insert(export.name.to_owned(), export.index);
                }
            }
        }
    }
    let mut lower = Lower {
        helpers,
        replaced: 0,
    };
    let mut module = Module::new();
    lower
        .parse_core_module(&mut module, Parser::new(0), &bytes)
        .map_err(|err| anyhow::anyhow!("{err}"))?;
    let output = module.finish();
    validate(&output)?;
    fs::write(&args[2], &output)?;
    println!(
        "Lowered {} float operations; {} -> {} bytes",
        lower.replaced,
        bytes.len(),
        output.len()
    );
    Ok(())
}
