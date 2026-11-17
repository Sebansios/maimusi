//! Developer tool: space text or evaluate the light model.
//!
//! hc-tool space <model.hspm> [--raw]        spaced lines from stdin
//! hc-tool eval  <model.hspm> <gold.txt>... [--raw] [--no-lexicon]
//!
//! `--raw` feeds whole sentences to the model (as the reference evaluation
//! did); without it, text goes through the IME's run/punctuation handling.

use hangul_core::{LightSpacer, NgramModel};
use std::io::{BufRead, Write};
use std::time::Instant;

fn cuts(s: &str) -> (Vec<usize>, usize) {
    let (mut pos, mut v) = (0, Vec::new());
    for c in s.chars() {
        if c == ' ' {
            v.push(pos);
        } else {
            pos += 1;
        }
    }
    v.dedup();
    (v, pos)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: hc-tool space|eval <model.hspm> [gold.txt...] [--raw] [--no-lexicon]");
        std::process::exit(2);
    }
    let raw = args.iter().any(|a| a == "--raw");
    let mut model = NgramModel::load(std::path::Path::new(&args[2])).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(1)
    });
    if args.iter().any(|a| a == "--no-lexicon") {
        model.set_lexicon(false);
    }
    let spacer = LightSpacer::new(model);
    let space = |s: &str| -> String {
        if raw {
            spacer.model.space_run(&s.replace(' ', ""))
        } else {
            spacer.space(&s.replace(' ', ""))
        }
    };
    match args[1].as_str() {
        "space" => {
            let stdout = std::io::stdout();
            let mut out = stdout.lock();
            for line in std::io::stdin().lock().lines() {
                let line = line.unwrap();
                writeln!(out, "{}", space(&line)).unwrap();
            }
        }
        "eval" => {
            for path in args[3..].iter().filter(|a| !a.starts_with("--")) {
                let text = std::fs::read_to_string(path).expect("read gold file");
                let (mut tp, mut fp, mut fnn, mut ok, mut n) = (0usize, 0usize, 0usize, 0usize, 0usize);
                let mut total_chars = 0usize;
                let t0 = Instant::now();
                for gold in text.lines().map(str::trim).filter(|l| !l.is_empty()) {
                    n += 1;
                    let pred = space(gold);
                    let (g, len) = cuts(gold);
                    let (p, _) = cuts(&pred);
                    total_chars += len;
                    if g == p {
                        ok += 1;
                    }
                    tp += p.iter().filter(|x| g.binary_search(x).is_ok()).count();
                    fp += p.iter().filter(|x| g.binary_search(x).is_err()).count();
                    fnn += g.iter().filter(|x| p.binary_search(x).is_err()).count();
                }
                let dt = t0.elapsed();
                let prec = tp as f64 / (tp + fp).max(1) as f64;
                let rec = tp as f64 / (tp + fnn).max(1) as f64;
                let f1 = if prec + rec > 0.0 { 2.0 * prec * rec / (prec + rec) } else { 0.0 };
                println!(
                    "{path}: sentences {n} | F1 {:.1}% (P {:.1} / R {:.1}) | exact {:.0}% | {:.1} µs/char",
                    f1 * 100.0,
                    prec * 100.0,
                    rec * 100.0,
                    ok as f64 * 100.0 / n.max(1) as f64,
                    dt.as_secs_f64() * 1e6 / total_chars.max(1) as f64
                );
            }
        }
        _ => {
            eprintln!("unknown command");
            std::process::exit(2);
        }
    }
}
