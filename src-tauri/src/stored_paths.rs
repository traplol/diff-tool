// Python persisted Unix filenames with undecodable bytes as JSON surrogate escapes.
// The webview uses Git's reversible display names. Translate paths only, keeping
// ordinary review text (including text that looks like an encoded name) intact.
use crate::git;
use std::fmt::Write;

pub fn python_string(text: &str) -> String {
    let quoted = serde_json::to_string(text).expect("strings serialize to JSON");
    let mut out = String::new();
    for c in quoted.chars() {
        if c < '\u{7f}' {
            out.push(c);
        } else {
            for unit in c.encode_utf16(&mut [0u16; 2]) {
                write!(out, "\\u{unit:04x}").unwrap();
            }
        }
    }
    out
}
pub fn stored_name(name: &str) -> Result<String, String> {
    let value = git::path_arg(name)?;
    let mut encoded = String::from("\"");
    for chunk in value.as_encoded_bytes().utf8_chunks() {
        let part = python_string(chunk.valid());
        encoded.push_str(&part[1..part.len() - 1]);
        for byte in chunk.invalid() {
            write!(encoded, "\\udc{byte:02x}").unwrap();
        }
    }
    encoded.push('"');
    Ok(encoded)
}
fn load_name(literal: &str) -> Result<String, String> {
    let decode = |raw: &str| serde_json::from_str::<String>(raw).map_err(|e| e.to_string());
    if let Ok(name) = decode(literal) {
        return Ok(git::name(name.as_bytes()));
    }
    let hex = |at: usize| {
        literal
            .get(at..at + 6)?
            .strip_prefix("\\u")
            .and_then(|s| u16::from_str_radix(s, 16).ok())
    };
    let mut bytes = Vec::new();
    let mut start = 1;
    let mut i = start;
    while i < literal.len() - 1 {
        if literal.as_bytes()[i] != b'\\' {
            i += 1;
            continue;
        }
        if let Some(unit) = hex(i) {
            if (0xdc80..=0xdcff).contains(&unit) {
                bytes.extend(decode(&format!("\"{}\"", &literal[start..i]))?.bytes());
                bytes.push((unit - 0xdc00) as u8);
                i += 6;
                start = i;
                continue;
            }
            if (0xd800..=0xdbff).contains(&unit)
                && hex(i + 6).is_some_and(|low| (0xdc00..=0xdfff).contains(&low))
            {
                i += 12;
                continue;
            }
        }
        i += 2;
    }
    bytes.extend(decode(&format!("\"{}\"", &literal[start..literal.len() - 1]))?.bytes());
    Ok(git::name(&bytes))
}
/// On legacy reads select either every array entry (stack) or the named note fields.
pub fn translate(raw: &str, stack: bool, loading: bool) -> Result<String, String> {
    if !raw.contains("␛git:") && !raw.contains("\\u") {
        return Ok(raw.into());
    }
    let bytes = raw.as_bytes();
    let mut out = String::new();
    let mut last = 0;
    let mut i = 0;
    let mut path_field = false;
    while i < bytes.len() {
        if bytes[i] != b'"' {
            i += 1;
            continue;
        }
        let start = i;
        i += 1;
        while i < bytes.len() && bytes[i] != b'"' {
            if bytes[i] == b'\\' {
                i += 1;
            }
            i += 1;
        }
        if i >= bytes.len() {
            return Err("Invalid string in saved review.".into());
        }
        i += 1;
        let literal = &raw[start..i];
        if raw[i..].trim_start().starts_with(':') {
            path_field = matches!(
                literal,
                "\"path\"" | "\"old_path\"" | "\"left\"" | "\"right\"" | "\"branch\""
            );
        } else if stack || path_field {
            let name = if loading {
                serde_json::to_string(&load_name(literal)?).map_err(|e| e.to_string())?
            } else {
                stored_name(&serde_json::from_str::<String>(literal).map_err(|e| e.to_string())?)?
            };
            out.push_str(&raw[last..start]);
            out.push_str(&name);
            last = i;
            path_field = false;
        }
    }
    out.push_str(&raw[last..]);
    Ok(out)
}
