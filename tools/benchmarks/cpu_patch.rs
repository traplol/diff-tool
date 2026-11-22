//! Headless worker for the Rust port's in-memory patch encoder.
#[path = "../../src-tauri/src/git/patch_data.rs"]
mod patch_data;

use std::hint::black_box;
use std::io::{self, Read, Write};
use std::time::Instant;

fn main() {
    let mut args = std::env::args().skip(1);
    let warmups: usize = args.next().expect("warmups").parse().expect("warmups");
    let samples: usize = args.next().expect("samples").parse().expect("samples");
    let mut section = Vec::new();
    io::stdin().read_to_end(&mut section).unwrap();
    let chunks = [section.as_slice()];
    let mut elapsed_ns = Vec::with_capacity(samples);
    for i in 0..warmups + samples {
        let start = Instant::now();
        let encoded = black_box(patch_data::encode(black_box(&chunks)));
        let elapsed = start.elapsed().as_nanos();
        if i >= warmups {
            elapsed_ns.push(elapsed);
        }
        drop(encoded);
    }

    // The first two lines are numeric JSON arrays. Write the compact patch
    // verbatim so the frontend can check its output against Python's rows.
    let (rows, starts) = patch_data::encode(&chunks);
    println!("{elapsed_ns:?}");
    println!("{starts:?}");
    io::stdout().lock().write_all(rows.as_bytes()).unwrap();
}
