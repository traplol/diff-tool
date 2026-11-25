use std::io::{self, BufRead, Write};

fn main() {
    let stdin = io::stdin();
    let mut input = stdin.lock();
    let mut line = String::new();
    if input.read_line(&mut line).unwrap() == 0 {
        return;
    }
    println!("{{\"id\":1,\"result\":{{\"protocol\":1,\"os\":\"windows\",\"pid\":{}}}}}", std::process::id());
    io::stdout().flush().unwrap();
    line.clear();
    if input.read_line(&mut line).unwrap() == 0 {
        return;
    }
    println!("{{\"id\":999,\"result\":null}}");
    io::stdout().flush().unwrap();
    loop {
        line.clear();
        if input.read_line(&mut line).unwrap() == 0 {
            break;
        }
    }
}
