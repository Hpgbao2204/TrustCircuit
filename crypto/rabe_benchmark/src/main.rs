use rabe::schemes::ac17::{cp_decrypt, cp_encrypt, cp_keygen, setup};
use rabe::utils::policy::pest::PolicyLanguage;
use std::env;
use std::process;
use std::time::Instant;

fn argument(name: &str, default: &str) -> String {
    let args: Vec<String> = env::args().collect();
    args.windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].clone())
        .unwrap_or_else(|| default.to_owned())
}

fn parse_sizes(value: &str) -> Result<Vec<usize>, String> {
    let sizes: Result<Vec<usize>, _> = value
        .split(',')
        .map(|part| part.trim().parse::<usize>())
        .collect();
    let sizes = sizes.map_err(|error| format!("invalid --policy-sizes: {error}"))?;
    if sizes.is_empty() || sizes.iter().any(|size| *size == 0) {
        return Err("policy sizes must be positive".to_owned());
    }
    Ok(sizes)
}

fn run() -> Result<(), String> {
    let sizes = parse_sizes(&argument("--policy-sizes", "5,10,15,20,25"))?;
    let repetitions = argument("--reps", "30")
        .parse::<usize>()
        .map_err(|error| format!("invalid --reps: {error}"))?;
    let warmups = argument("--warmups", "5")
        .parse::<usize>()
        .map_err(|error| format!("invalid --warmups: {error}"))?;
    let payload_bytes = argument("--payload-bytes", "32")
        .parse::<usize>()
        .map_err(|error| format!("invalid --payload-bytes: {error}"))?;
    if repetitions == 0 || payload_bytes == 0 {
        return Err("repetitions and payload size must be positive".to_owned());
    }

    let plaintext = vec![0x54_u8; payload_bytes];
    let (public_key, master_key) = setup();
    let mut output = String::from(
        "implementation,scheme,operation,policy_attributes,repetition,payload_bytes,latency_ms,success\n",
    );

    for attribute_count in sizes {
        let attributes: Vec<String> = (1..=attribute_count)
            .map(|index| format!("A{index:03}"))
            .collect();
        let attribute_refs: Vec<&str> = attributes.iter().map(String::as_str).collect();
        let mut policy = format!("\"{}\"", attributes[0]);
        for attribute in attributes.iter().skip(1) {
            policy = format!("({policy} and \"{attribute}\")");
        }
        let secret_key = cp_keygen(&master_key, &attribute_refs)
            .map_err(|error| format!("keygen failed for {attribute_count} attributes: {error}"))?;

        for _ in 0..warmups {
            let ciphertext = cp_encrypt(
                &public_key,
                &policy,
                &plaintext,
                PolicyLanguage::HumanPolicy,
            )
            .map_err(|error| format!("warm-up encryption failed: {error}"))?;
            let recovered = cp_decrypt(&secret_key, &ciphertext)
                .map_err(|error| format!("warm-up decryption failed: {error}"))?;
            if recovered != plaintext {
                return Err("warm-up plaintext mismatch".to_owned());
            }
        }

        for repetition in 0..repetitions {
            let encrypt_start = Instant::now();
            let ciphertext = cp_encrypt(
                &public_key,
                &policy,
                &plaintext,
                PolicyLanguage::HumanPolicy,
            )
            .map_err(|error| format!("encryption failed: {error}"))?;
            let encrypt_ms = encrypt_start.elapsed().as_secs_f64() * 1000.0;

            let decrypt_start = Instant::now();
            let recovered = cp_decrypt(&secret_key, &ciphertext)
                .map_err(|error| format!("decryption failed: {error}"))?;
            let decrypt_ms = decrypt_start.elapsed().as_secs_f64() * 1000.0;
            let success = recovered == plaintext;
            if !success {
                return Err(format!(
                    "plaintext mismatch at attributes={attribute_count}, repetition={repetition}"
                ));
            }

            output.push_str(&format!(
                "full_cpabe,AC17_FAME_rabe_0.4.2,encrypt,{attribute_count},{repetition},{payload_bytes},{encrypt_ms:.6},true\n"
            ));
            output.push_str(&format!(
                "full_cpabe,AC17_FAME_rabe_0.4.2,decrypt,{attribute_count},{repetition},{payload_bytes},{decrypt_ms:.6},true\n"
            ));
        }
    }

    print!("{output}");
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        process::exit(1);
    }
}
