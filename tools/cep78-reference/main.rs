//! Independent fixtures; record and entrypoint definitions are extracted from pinned Rust.
#![allow(dead_code)]
use casper_types::{CLType, CLValue, Key, Parameter, EntityEntryPoint as EntryPoint,
    EntryPointAccess, EntryPointType, EntryPointPayment, EntryPoints,
    bytesrepr::ToBytes};
use casper_event_standard::Schemas;
use serde_json::{json, Value};
use std::collections::BTreeMap;
mod constants;
mod events;
mod metadata;
use constants::*;
use events::*;
include!("entry_points.rs");
fn cl<T: casper_types::CLTyped + ToBytes>(value: T) -> String {
    hex::encode(CLValue::from_t(value).unwrap().to_bytes().unwrap())
}
fn ty(value: &CLType) -> String {
    hex::encode(&CLValue::from_components(value.clone(), vec![]).to_bytes().unwrap()[4..])
}
fn event<T: ToBytes + serde::Serialize>(name: &str, value: T) -> Value {
    let text = serde_json::to_string(&value).unwrap();
    json!({"name":name, "ces":hex::encode(value.to_bytes().unwrap()), "json":text,
        "native_string":hex::encode(casper_types::contract_messages::MessagePayload::String(text.clone()).to_bytes().unwrap()),
        "native_bytes":hex::encode(casper_types::contract_messages::MessagePayload::Bytes(text.into_bytes().into()).to_bytes().unwrap())})
}
fn main() {
    let owner = Key::Account(casper_types::account::AccountHash::new([0x11; 32]));
    let spender = Key::Hash([0x22; 32]);
    let recipient = Key::Account(casper_types::account::AccountHash::new([0x33; 32]));
    let token_id = "42".to_string();
    let data = "{\"name\":\"Token 🦀 é\",\"symbol\":\"NFT\",\"token_uri\":\"ipfs://example\"}".to_string();
    let events = vec![
        event("Mint", Mint{recipient,token_id:token_id.clone(),data:data.clone()}),
        event("Burn", Burn{owner,token_id:token_id.clone(),burner:spender}),
        event("Approval", Approval{owner,spender,token_id:token_id.clone()}),
        event("ApprovalRevoked", ApprovalRevoked{owner,token_id:token_id.clone()}),
        event("ApprovalForAll", ApprovalForAll{owner,operator:spender}),
        event("RevokedForAll", RevokedForAll{owner,operator:spender}),
        event("Transfer", Transfer{owner,spender:Some(spender),recipient,token_id:token_id.clone()}),
        event("Transfer", Transfer{owner,spender:None,recipient,token_id:token_id.clone()}),
        event("MetadataUpdated", MetadataUpdated{token_id:token_id.clone(),data:data.clone()}),
        event("MetadataUpdated", MetadataUpdated{token_id:token_id.clone(),data:"line\n\t\u{8} 🦀".to_string()}),
        event("VariablesSet", VariablesSet{}), event("Migration", Migration{}),
    ];
    let schemas = Schemas::new().with::<Mint>().with::<Burn>().with::<Approval>()
        .with::<ApprovalRevoked>().with::<ApprovalForAll>().with::<RevokedForAll>()
        .with::<Transfer>().with::<MetadataUpdated>().with::<VariablesSet>().with::<Migration>();
    let eps = generate_entry_points();
    let abi = eps.clone().take_entry_points().into_iter().map(|ep| json!({
        "name":ep.name(), "args":ep.args().iter().map(|p|json!({"name":p.name(),"cl_type":ty(p.cl_type())})).collect::<Vec<_>>(),
        "returns":ty(ep.ret())})).collect::<Vec<_>>();
    let mut pair = owner.to_bytes().unwrap(); pair.extend(spender.to_bytes().unwrap());
    let uref = casper_types::URef::new([0x44;32],casper_types::AccessRights::READ_ADD_WRITE);
    let mut strings = BTreeMap::new();
    strings.insert("z".to_string(), "line\n\t\u{8}".to_string());
    strings.insert("a".to_string(), "🦀 é \" \\".to_string());
    let parsed721: metadata::MetadataNFT721 = serde_json::from_str(&data).unwrap();
    let data78 = "{\"checksum\":\"abcd\",\"name\":\"Token\",\"token_uri\":\"ipfs://example\"}";
    let parsed78: metadata::MetadataCEP78 = serde_json::from_str(data78).unwrap();
    println!("{}",serde_json::to_string_pretty(&json!({
        "upstream":{"url":"https://github.com/casper-ecosystem/cep-78-enhanced-nft","version":"2.0.0","commit":"9a624aa9a4f5cba59260f93652b76948e528c7f2"},
        "abi":abi,"entry_points":hex::encode(eps.to_bytes().unwrap()),"ces_schemas":cl(schemas),"events":events,
        "dictionary":{"address":"11".repeat(32),"operator":hex::encode(casper_types::Digest::hash(pair).as_ref())},
        "values":{"register":cl(("My NFT".to_string(),uref)),"mint":cl(("receipt".to_string(),recipient,"42".to_string())),"receipts":cl(vec![("receipt".to_string(),recipient)])},
        "metadata":[{"kind":1,"input":data,"expected":serde_json::to_string_pretty(&parsed721).unwrap()},
            {"kind":0,"input":data78,"expected":serde_json::to_string_pretty(&parsed78).unwrap()},
            {"kind":3,"input":serde_json::to_string(&strings).unwrap(),"expected":serde_json::to_string_pretty(&strings).unwrap()}]
    })).unwrap());
}
