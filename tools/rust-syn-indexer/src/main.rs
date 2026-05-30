use std::io::{self, Read};

use proc_macro2::TokenStream;
use quote::ToTokens;
use serde::Serialize;
use syn::spanned::Spanned;
use syn::{Attribute, ImplItem, Item, Visibility};

#[derive(Serialize)]
struct IndexedItem {
    kind: String,
    name: String,
    #[serde(rename = "pub")]
    is_pub: bool,
    signature: String,
    doc: Option<String>,
    is_test: bool,
    body_start: u32,
    body_end: u32,
}

#[derive(Serialize)]
struct Output {
    items: Vec<IndexedItem>,
}

fn main() {
    let mut src = String::new();
    io::stdin().read_to_string(&mut src).expect("read stdin");

    let file = syn::parse_file(&src).expect("parse Rust source");

    let mut items = Vec::new();
    collect_items(&file.items, &mut items);

    println!("{}", serde_json::to_string_pretty(&Output { items }).unwrap());
}

fn fmt_tokens(node: &impl ToTokens) -> String {
    let mut ts = TokenStream::new();
    node.to_tokens(&mut ts);
    ts.to_string()
}

fn is_pub(vis: &Visibility) -> bool {
    matches!(vis, Visibility::Public(_))
}

fn extract_doc(attrs: &[Attribute]) -> Option<String> {
    for attr in attrs {
        if attr.path().is_ident("doc") {
            if let syn::Meta::NameValue(nv) = &attr.meta {
                if let syn::Expr::Lit(expr) = &nv.value {
                    if let syn::Lit::Str(s) = &expr.lit {
                        let v = s.value();
                        let trimmed = v.trim().to_string();
                        if !trimmed.is_empty() {
                            return Some(trimmed);
                        }
                    }
                }
            }
        }
    }
    None
}

fn has_test_attr(attrs: &[Attribute]) -> bool {
    for attr in attrs {
        let path = attr.path();
        if path.is_ident("test") {
            return true;
        }
        if path.segments.len() == 2
            && path.segments[0].ident == "tokio"
            && path.segments[1].ident == "test"
        {
            return true;
        }
    }
    false
}

fn collect_items(items: &[Item], out: &mut Vec<IndexedItem>) {
    for item in items {
        match item {
            Item::Fn(f) => {
                let span = f.span();
                let sig = format!("{} {}", fmt_tokens(&f.vis), fmt_tokens(&f.sig));
                out.push(IndexedItem {
                    kind: "fn".into(),
                    name: f.sig.ident.to_string(),
                    is_pub: is_pub(&f.vis),
                    signature: sig.trim().to_string(),
                    doc: extract_doc(&f.attrs),
                    is_test: has_test_attr(&f.attrs),
                    body_start: span.start().line as u32,
                    body_end: span.end().line as u32,
                });
            }
            Item::Struct(s) => {
                let span = s.span();
                let sig = format!(
                    "{} struct {}{}",
                    fmt_tokens(&s.vis),
                    s.ident,
                    fmt_tokens(&s.generics)
                );
                out.push(IndexedItem {
                    kind: "struct".into(),
                    name: s.ident.to_string(),
                    is_pub: is_pub(&s.vis),
                    signature: sig.trim().to_string(),
                    doc: extract_doc(&s.attrs),
                    is_test: false,
                    body_start: span.start().line as u32,
                    body_end: span.end().line as u32,
                });
            }
            Item::Enum(e) => {
                let span = e.span();
                let sig = format!(
                    "{} enum {}{}",
                    fmt_tokens(&e.vis),
                    e.ident,
                    fmt_tokens(&e.generics)
                );
                out.push(IndexedItem {
                    kind: "enum".into(),
                    name: e.ident.to_string(),
                    is_pub: is_pub(&e.vis),
                    signature: sig.trim().to_string(),
                    doc: extract_doc(&e.attrs),
                    is_test: false,
                    body_start: span.start().line as u32,
                    body_end: span.end().line as u32,
                });
            }
            Item::Trait(t) => {
                let span = t.span();
                let sig = format!(
                    "{} trait {}{}",
                    fmt_tokens(&t.vis),
                    t.ident,
                    fmt_tokens(&t.generics)
                );
                out.push(IndexedItem {
                    kind: "trait".into(),
                    name: t.ident.to_string(),
                    is_pub: is_pub(&t.vis),
                    signature: sig.trim().to_string(),
                    doc: extract_doc(&t.attrs),
                    is_test: false,
                    body_start: span.start().line as u32,
                    body_end: span.end().line as u32,
                });
            }
            Item::Impl(i) => {
                let span = i.span();
                let name = match &i.trait_ {
                    Some((_, trait_, _)) => format!(
                        "impl {} for {}",
                        fmt_tokens(trait_),
                        fmt_tokens(i.self_ty.as_ref())
                    ),
                    None => format!("impl {}", fmt_tokens(i.self_ty.as_ref())),
                };
                out.push(IndexedItem {
                    kind: "impl".into(),
                    name: name.clone(),
                    is_pub: false,
                    signature: name,
                    doc: extract_doc(&i.attrs),
                    is_test: false,
                    body_start: span.start().line as u32,
                    body_end: span.end().line as u32,
                });
                for impl_item in &i.items {
                    if let ImplItem::Fn(method) = impl_item {
                        let mspan = method.span();
                        let sig = format!(
                            "{} {}",
                            fmt_tokens(&method.vis),
                            fmt_tokens(&method.sig)
                        );
                        out.push(IndexedItem {
                            kind: "fn".into(),
                            name: method.sig.ident.to_string(),
                            is_pub: is_pub(&method.vis),
                            signature: sig.trim().to_string(),
                            doc: extract_doc(&method.attrs),
                            is_test: has_test_attr(&method.attrs),
                            body_start: mspan.start().line as u32,
                            body_end: mspan.end().line as u32,
                        });
                    }
                }
            }
            Item::Type(t) => {
                let span = t.span();
                let sig = format!("{} type {}", fmt_tokens(&t.vis), t.ident);
                out.push(IndexedItem {
                    kind: "type".into(),
                    name: t.ident.to_string(),
                    is_pub: is_pub(&t.vis),
                    signature: sig.trim().to_string(),
                    doc: extract_doc(&t.attrs),
                    is_test: false,
                    body_start: span.start().line as u32,
                    body_end: span.end().line as u32,
                });
            }
            Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    collect_items(items, out);
                }
            }
            _ => {}
        }
    }
}
