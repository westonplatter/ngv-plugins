# Implied Volatility Inversion — Research Notes

Audience: building a Python-fronted, Rust/C-backed batch IV engine that
handles European, American, futures (Black-76), and dividend-paying equity
options, optimized for vectorized throughput.

---

## 1. The problem, framed precisely

Given an observed option price `P_mkt` and inputs `(S, K, T, r, q, type)`
(or `(F, K, T, r, type)` for futures), implied volatility `σ_IV` is the
unique value that satisfies

```
Model(σ_IV; S, K, T, r, q, type) = P_mkt
```

This is a 1-D root-finding problem. Two facts make it tractable:

1. **Monotonicity.** For Black-Scholes / Black-76, `∂P/∂σ = vega > 0` on
   the interior of the valid `σ` range, so the root is unique when it
   exists.
2. **Tight bounds.** Arbitrage bounds give a finite interval where the
   root must live:
   - Call:  `max(0, F·D - K·D) ≤ C ≤ F·D`  where  `D = e^{-rT}`,  `F = S·e^{(r-q)T}`
   - Put:   `max(0, K·D - F·D) ≤ P ≤ K·D`
   - Equivalently in undiscounted terms, IV exists iff the *time value*
     (`P - intrinsic`) is strictly positive and less than the upper bound.

For American options the same monotonicity holds in `σ` (early-exercise
premium is increasing in vol), but there is no closed-form pricer, so
each function evaluation is more expensive.

---

## 2. Preprocess: arbitrage / boundary handling

Do this **before** running any iteration. It is the source of most
production bugs.

| Condition | Action |
|---|---|
| `T ≤ 0` or `σ undefined` | return `NaN` |
| `P_mkt < intrinsic - ε` | violates lower bound → return `NaN` (or flag) |
| `P_mkt ≈ intrinsic` | IV → 0, return 0 (or `NaN` per convention) |
| `P_mkt ≥ upper_bound - ε` | IV → ∞, return `NaN` or sentinel |
| Deep ITM / OTM | invert the **out-of-the-money** side via put-call parity for numerical stability — wings have tiny vega and explode under Newton |

The OTM-side trick: for a call with `K < F`, parity says
`C = P + (F − K)·D`. Recover the OTM put price and invert that instead;
its vega is identical but the price is much smaller relative to noise.

For bid/ask data, the right convention depends on use:
- Three quotes: `iv_bid`, `iv_mid`, `iv_ask`. Lets downstream code know
  the noise floor.
- If quote is crossed/locked or one side violates arbitrage, only return
  the valid side.

---

## 3. Algorithms — comparison

### 3.1 Iterative root-finders

| Method | Order | Per-iter cost | Robustness | Vectorizes? |
|---|---|---|---|---|
| Bisection | 1 | 1 pricer | bulletproof | yes, same iters/element |
| Secant | ~1.6 | 1 pricer | medium | yes |
| Newton (vega) | 2 | 1 pricer + vega | fails near vega ≈ 0 | yes |
| Halley (vega, vomma) | 3 | 1 pricer + 2 derivs | better than Newton | yes |
| Householder-4 (used by Jäckel) | 4 | 1 pricer + 3 derivs | excellent w/ good init | yes |
| Brent (SciPy `brentq`) | superlinear | 1 pricer | bulletproof, fast | poorly — per-element iter counts vary |

Newton-Raphson is the default workhorse. The recurrence is

```
σ_{n+1} = σ_n − (Model(σ_n) − P_mkt) / vega(σ_n)
```

Two pitfalls in practice:
- **Vega collapse.** Deep ITM/OTM and near-expiry options have vega
  ≈ 0; one Newton step throws σ to absurd values. Fixes: clamp the step,
  switch to bisection on overshoot, or invert OTM side (see above).
- **Initial guess.** Bad seeds cause non-convergence even on benign
  cases. Use a closed-form approximation as the seed.

### 3.2 Closed-form / non-iterative approximations

Useful both as **standalone fast paths** (when you can tolerate ~1–5%
error) and as **initial guesses** for Newton/Householder.

- **Brenner–Subrahmanyam (1988):** `σ ≈ √(2π/T) · C/S`. Only accurate
  near ATM.
- **Manaster–Koehler (1982):** initial guess proven to make Newton
  converge monotonically — historically important.
- **Corrado–Miller (1996):** ATM-centric refinement, ~1% near ATM.
- **Li (2005):** rational-function fit, narrow but very fast.
- **Stefanica–Radoičić (2017), "An Explicit Implied Volatility
  Formula":** explicit formula with proven <10% relative error across
  *all* strikes and maturities. The current best non-iterative
  approximation. Excellent as a Newton/Householder seed; one Newton
  step from this seed typically reaches 1e-12.
- **Matic–Radoičić–Stefanica Pólya-based ATM-forward (2017):** very
  tight ATM, used as a building block.

### 3.3 Jäckel "Let's Be Rational" (2015) — state of the art for European/Black

Reference: P. Jäckel, *Let's Be Rational*, Wilmott (2015).
[jaeckel.org/LetsBeRational.pdf](http://www.jaeckel.org/LetsBeRational.pdf)

The algorithm is **non-iterative in the iteration-count sense**: it is
exactly three steps —

1. A carefully constructed initial guess from matched asymptotic
   expansions, valid uniformly across the entire no-arbitrage region
   (including the wings where Newton normally dies).
2. One Householder-4 (4th-order) step.
3. One more Householder-4 step.

Properties:
- Reaches full IEEE-754 double precision for *all* valid inputs.
- Sub-microsecond per option in optimized C++ / Rust.
- Works on the "normalized Black" parameterization (only depends on
  `x = ln(F/K)` and total variance `σ²T`), so it transparently covers
  Black-Scholes, Black-76, and dividend cases once you compute
  `F = S·e^{(r-q)T}` and `D = e^{-rT}`.
- 2024 update from Jäckel ("PJ-2024-Inverse-Normal") ships a faster
  inverse-normal-CDF, ~20–30% throughput win.

**This is the algorithm to use for everything Black-family.** Two
mature open-source implementations:
- C: `py_lets_be_rational` (`vollib` org), reference SWIG-wrapped port.
- Rust: `nakashima-hikaru/implied-vol`, a pure-Rust port that hits
  parity with Jäckel's C++ reference on accuracy and is in the same
  performance envelope.

### 3.4 American options — no closed form, harder

Pricing model is the hard part; once you have a pricer the IV inversion
is just Newton/Brent on top.

| Pricer | Speed | Accuracy | Vectorizable? |
|---|---|---|---|
| Binomial (CRR/Tian) | slow (O(N²)) | converges to truth | partially |
| Trinomial | slow | similar | partially |
| PDE / Crank-Nicolson | slow | excellent | partially |
| Barone–Adesi–Whaley (1987) | fast | ~1% error, breaks on dividends | yes |
| **Bjerksund–Stensland 2002** | **very fast** | **<0.1% vs binomial typical** | **yes** |
| Longstaff–Schwartz (MC) | slow | flexible | yes but noisy |
| Neural surrogate | very fast | depends on training | yes |

**Bjerksund–Stensland 2002 + finite-difference vega + vectorized
Newton** is the standard production sweet spot for American IV. Use
bump-and-reprice for vega (`bump = 1e-4`) and clamp the Newton step.
Fall back to Brent on non-convergence (rare with a Stefanica–Radoičić
seed).

One gotcha worth being explicit about: "American implied volatility"
is not the same number as the corresponding European IV. The
early-exercise premium is baked into σ. If downstream code wants to
fit smiles, decide upfront whether the engine returns European-equivalent
IV (de-Americanized) or the raw American IV.

### 3.5 ML / neural surrogates

Recent work (e.g. "Newton-Raphson Emulation Network",
[arXiv:2210.15969](https://arxiv.org/abs/2210.15969); fastvol's neural
surrogate matching Bjerksund–Stensland on American puts) shows that
small MLPs can amortize the inversion to a single forward pass.

Verdict for your use case: probably overkill. Jäckel is already
sub-microsecond per option in Rust; the only reason to reach for a
neural surrogate is if you have tens of millions of American options
per batch and BS-2002 + Newton is your bottleneck.

---

## 4. Recommended algorithmic stack

Given you said vectorized throughput is the priority and you'll
implement in Rust:

```
                ┌─ European calls/puts  ──► Jäckel "Let's Be Rational"
                │                            (Householder-4, 2 steps)
                │
Input batch ────┼─ Black-76 / futures  ──► same algorithm
                │   (same code path via F-parameterization)
                │
                ├─ Dividend equity     ──► same code path
                │   (compute F = S·e^{(r-q)T} up front)
                │
                └─ American           ──► Bjerksund–Stensland 2002
                                          + vectorized Newton w/ FD vega
                                          (seed: Stefanica–Radoičić)
                                          + Brent fallback on failure
```

Single Rust entry point per batch; option style dispatched per-element
or via separate kernels.

---

## 5. Vectorization & batch architecture

Three orthogonal levels of parallelism, all worth using:

1. **Algorithm-level** — fixed-iteration algorithms (Jäckel: always
   exactly 2 Householder steps; BS-2002: closed-form-ish) vectorize
   trivially because every element does the same work. Variable-
   iteration algorithms (Brent) are SIMD-hostile.
2. **SIMD** — Rust has `std::simd` (portable-simd, nightly) or stable
   crates `wide` / `pulp`. Black-family math is dominated by `erf`,
   `exp`, `log`; use vectorized special-function libraries (`sleef`,
   `vectorize`, or hand-rolled polynomial cores). 4–8× single-thread
   speedup is realistic.
3. **Thread-level** — Rayon's `par_chunks_mut` over the batch. Cheap,
   linear scaling up to memory bandwidth.

GPU is worth it only at very large batch sizes (≥10⁶) and is a separate
project. CPU SIMD + threads will hit 100M+ European IVs/sec on a modern
desktop CPU.

### Memory layout

Use **struct-of-arrays**, not array-of-structs:

```rust
pub struct OptionBatch<'a> {
    pub forward:     &'a [f64],  // pre-computed F = S·exp((r-q)T)
    pub strike:      &'a [f64],
    pub ttm:         &'a [f64],
    pub discount:    &'a [f64],  // pre-computed D = exp(-rT)
    pub price:       &'a [f64],
    pub is_call:     &'a [bool], // or pack into bitset
    pub style:       &'a [Style], // European | Black76 | American
}
```

SoA gives clean SIMD lanes, contiguous memory access, and zero-copy
NumPy interop via the `numpy` crate (`PyReadonlyArray1<f64>`).

---

## 6. Concrete Python + Rust architecture

```
my_iv/
├── Cargo.toml          # crate-type = ["cdylib"]
├── pyproject.toml      # maturin build backend
├── src/
│   ├── lib.rs          # #[pymodule], PyO3 bindings
│   ├── black.rs        # normalized Black price + greeks
│   ├── lets_be_rational.rs   # Jäckel's algorithm
│   ├── bjerksund_stensland.rs # American pricer
│   ├── inverse.rs      # batch IV inversion dispatcher
│   └── arbitrage.rs    # bounds checks, edge cases
└── python/my_iv/
    └── __init__.py     # thin Python wrapper, dtype coercion
```

Stack choices:

- **Bindings:** PyO3 + maturin. Zero-copy NumPy via `numpy` crate
  (rust-numpy). Avoid GIL holding on the hot loop — use
  `py.allow_threads(|| ... )` around the Rust kernel.
- **Reference Rust port:** start from
  `nakashima-hikaru/implied-vol` (MIT/Apache, faithful Jäckel port)
  rather than rewriting Householder-4 from the paper. Saves weeks.
- **Build:** `maturin develop --release` for local; publish wheels via
  cibuildwheel + maturin GitHub Action.
- **Testing:** golden-file tests against
  `py_lets_be_rational` for European, against QuantLib's binomial for
  American. Stress with adversarial inputs: `T=1/365`, `|ln(F/K)| > 5`,
  prices at machine-ε from intrinsic.

### API sketch

```python
import numpy as np
from my_iv import implied_vol

# Single call form
iv = implied_vol(
    price=1.25, forward=100.0, strike=105.0,
    ttm=0.25, rate=0.04, is_call=True, style="european",
)

# Batch form — all args broadcast like NumPy ufuncs
ivs = implied_vol(
    price=prices_arr, forward=F_arr, strike=K_arr,
    ttm=T_arr, rate=r_arr, is_call=type_arr, style="european",
)

# Bid/ask: returns structured result
res = implied_vol_quotes(
    bid=bid_arr, ask=ask_arr, ...
)
# res.bid, res.mid, res.ask, res.flags
```

Reasonable conventions:
- Inputs accept either `(S, q)` or `F` directly; the wrapper computes
  `F` if needed.
- Return `NaN` for unsolvable; expose a parallel `flags` array
  identifying *why* (`OK`, `BELOW_INTRINSIC`, `ABOVE_UPPER`,
  `NEAR_EXPIRY`, `NON_CONVERGED`).

---

## 7. Build-vs-buy tiers

In order of effort:

**Tier 1 — wrap and ship (1–2 days)**
- `py_vollib_vectorized` for European/Black-76 + dividends.
- Add a thin Python `bjerksund_stensland_2002` + Brent for American.
- Pro: working tomorrow. Con: pure-Python American path is slow.

**Tier 2 — Rust kernel, your bindings (1–2 weeks)**
- Vendor `nakashima-hikaru/implied-vol` for Jäckel.
- Implement Bjerksund–Stensland 2002 in Rust (the formulas are
  algebraic, ~150 LOC).
- PyO3 + maturin glue, SoA batch API.
- This is the recommended balance for a serious engine.

**Tier 3 — bespoke SIMD + multi-threaded (1–2 months)**
- Hand-vectorize Black math with `wide`/`pulp` and a fast `erf`/`exp`.
- Rayon over batches.
- Optional CUDA kernel.
- Evaluate `vgalanti/fastvol` first — it already does SIMD + OpenMP +
  CUDA for European AND American and may obviate building this from
  scratch.

---

## 8. Edge-case checklist (don't ship without these tests)

- `T = 0`, `T < 0`
- `S = 0`, `K = 0`
- `price = 0`, `price = intrinsic`, `price = intrinsic - ε`,
  `price = upper_bound`, `price = upper_bound + ε`
- Deep ITM / OTM: `|ln(F/K)|` up to ~10
- Near-expiry: `T = 1 day`, `1 hour`
- Negative rates (yes, this is real for EUR / JPY history)
- Very high vol (σ > 5.0): exotic / crypto
- Very low vol (σ < 0.01): short-rates options
- NaN / Inf in inputs — must not crash, must propagate
- Put-call parity round-trip: invert call IV, reprice put with parity,
  must match input put price

---

## 9. Open questions worth deciding before coding

1. **De-Americanization.** For American options, return raw American
   IV or convert to European-equivalent for smile fitting?
2. **Dividend model.** Continuous `q`, or discrete cash dividends? The
   latter breaks Black-Scholes closed-form and pushes you to escrow /
   Bos–Vandermark adjustments or to a tree.
3. **Rate curve vs scalar `r`.** A single `r` per option is fine for
   exchange-listed equity options; for longer-dated or rates products
   you need a discount curve per pricing.
4. **Greek delivery.** Should the engine return greeks (delta, gamma,
   vega, theta, rho) alongside IV in the same call? Cheap to add once
   the pricer is in place.
5. **Quote convention.** IV from mid, or always return `(bid_iv, ask_iv)`
   and let the caller decide?
6. **Precision target.** Full machine precision (Jäckel), or is 1e-6
   enough? The latter opens up the explicit-formula fast paths
   (Stefanica–Radoičić alone, no Newton).
7. **Failure mode contract.** Return `NaN` silently, or `(value, flag)`
   tuple, or raise? Affects vectorized usability.

---

## 10. Reference reading

- Jäckel, *Let's Be Rational* — [jaeckel.org/LetsBeRational.pdf](http://www.jaeckel.org/LetsBeRational.pdf)
- Jäckel, *By Implication* (2006) — predecessor algorithm.
- Stefanica & Radoičić, *An Explicit Implied Volatility Formula*,
  IJTAF (2017) — [SSRN 2908494](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2908494)
- Bjerksund & Stensland, *Closed Form Valuation of American Options*
  (2002).
- `nakashima-hikaru/implied-vol` — Rust Jäckel port.
- `vollib` / `py_lets_be_rational` — C Jäckel port with Python wrapper.
- `vgalanti/fastvol` — production SIMD + CUDA + neural example.
- `dedwards25/Python_Option_Pricing` — GBS + BS-1993/2002 reference
  Python.
