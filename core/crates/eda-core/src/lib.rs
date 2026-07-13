//! Core primitives for the Unified EDA Platform.
//!
//! Placeholder for Phase 1 (the design database).
//! See `docs/eda_platform_roadmap.md`.

/// Returns a friendly identifier - placeholder for the first real module.
pub fn hello() -> &'static str {
    "eda-core ready"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hello_works() {
        assert_eq!(hello(), "eda-core ready");
    }
}
