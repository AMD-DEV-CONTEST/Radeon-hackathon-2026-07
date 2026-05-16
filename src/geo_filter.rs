//! Geological Subtraction Filter — removes natural magnetic background
//! to isolate anthropogenic anomalies (wrecks, pipes, cables).
//!
//! Pipeline:
//! 1. FFT raw aeromagnetic grid to frequency domain
//! 2. Bandpass filter removes geology (low freq) and sensor noise (very high freq)
//! 3. IFFT back to spatial domain → anthropogenic residual
//! 4. Detect dipoles in residual (positive-negative pairs = man-made)
//! 5. Classify with aspect ratio (elongated = wreck, vertical = wellhead)

use std::f64::consts::PI;

/// Configuration for the geological bandpass filter.
#[derive(Debug, Clone)]
pub struct GeologicalFilter {
    /// Low-frequency cutoff — removes large geology (basalt flows, bedrock)
    /// Typical: 0.01 - 0.05 cycles/meter
    pub low_cutoff: f64,
    /// High-frequency cutoff — removes sensor noise
    /// Typical: 0.5 - 2.0 cycles/meter
    pub high_cutoff: f64,
    /// Transition bandwidth (smooth rolloff to avoid ringing)
    pub rolloff_width: f64,
}

impl Default for GeologicalFilter {
    fn default() -> Self {
        Self {
            low_cutoff: 0.02,    // Remove features > 50m wavelength (geology)
            high_cutoff: 1.0,    // Remove features < 1m wavelength (noise)
            rolloff_width: 0.01, // Smooth transition
        }
    }
}

/// A candidate dipole anomaly detected in the residual.
#[derive(Debug, Clone)]
pub struct DipoleCandidate {
    /// Grid position (row, col) of the dipole center
    pub center: (usize, usize),
    /// Positive peak amplitude (nanoTesla)
    pub positive_peak: f64,
    /// Negative peak amplitude (nanoTesla)
    pub negative_peak: f64,
    /// Separation between positive and negative peaks (in grid cells)
    pub separation: f64,
    /// Estimated physical separation in meters
    pub separation_meters: f64,
    /// Confidence score (0.0 - 1.0)
    pub confidence: f64,
    /// Dominant direction (radians from north)
    pub direction: f64,
}

/// Target classification based on aspect ratio and dipole characteristics.
#[derive(Debug, Clone, PartialEq)]
pub enum TargetType {
    /// Elongated horizontal structure — likely a wreck
    ElongatedHorizontal,
    /// Vertical structure — likely wellhead or pipes
    VerticalStructure,
    /// Ambiguous blob — needs more data
    UnknownBlob,
    /// Galvanic cell signature — lead/steel in mineral water
    GalvanicDipole,
}

impl GeologicalFilter {
    /// Apply the bandpass filter to a 2D grid of aeromagnetic data.
    /// Returns the anthropogenic residual (geology removed).
    pub fn filter_geology(&self, grid: &[f64], rows: usize, cols: usize) -> Vec<f64> {
        // 1. Forward FFT (2D via row-then-column approach)
        let freq_domain = fft_2d(grid, rows, cols);

        // 2. Apply bandpass mask
        let filtered = self.apply_bandpass(&freq_domain, rows, cols);

        // 3. Inverse FFT back to spatial domain
        let residual = ifft_2d(&filtered, rows, cols);

        residual
    }

    /// Apply bandpass filter in frequency domain.
    fn apply_bandpass(&self, freq_data: &[Complex], rows: usize, cols: usize) -> Vec<Complex> {
        let mut filtered = freq_data.to_vec();
        let center_row = rows / 2;
        let center_col = cols / 2;

        for row in 0..rows {
            for col in 0..cols {
                let dy = (row as f64 - center_row as f64) / rows as f64;
                let dx = (col as f64 - center_col as f64) / cols as f64;
                let freq = (dx * dx + dy * dy).sqrt();

                // Butterworth-style bandpass
                let gain = bandpass_gain(freq, self.low_cutoff, self.high_cutoff, self.rolloff_width);
                let idx = row * cols + col;
                filtered[idx].re *= gain;
                filtered[idx].im *= gain;
            }
        }

        filtered
    }

    /// Detect dipole anomalies in the filtered residual.
    /// A dipole is a positive-negative pair separated by 5-200 meters.
    pub fn detect_dipoles(
        &self,
        residual: &[f64],
        rows: usize,
        cols: usize,
        cell_size_meters: f64,
    ) -> Vec<DipoleCandidate> {
        let mut candidates = Vec::new();
        let threshold = compute_threshold(residual, 3.0); // 3-sigma detection

        // Find local maxima (positive peaks)
        let maxima = find_local_extrema(residual, rows, cols, true, threshold);
        // Find local minima (negative peaks)
        let minima = find_local_extrema(residual, rows, cols, false, -threshold);

        // Match positive-negative pairs
        for max_pos in &maxima {
            for min_pos in &minima {
                let dr = max_pos.0 as f64 - min_pos.0 as f64;
                let dc = max_pos.1 as f64 - min_pos.1 as f64;
                let separation = (dr * dr + dc * dc).sqrt();
                let separation_meters = separation * cell_size_meters;

                // Anthropogenic dipoles: 5-200m separation
                if separation_meters >= 5.0 && separation_meters <= 200.0 {
                    let direction = dr.atan2(dc);
                    let pos_val = residual[max_pos.0 * cols + max_pos.1];
                    let neg_val = residual[min_pos.0 * cols + min_pos.1];

                    // Confidence based on symmetry (equal amplitude = higher confidence)
                    let amplitude_ratio = pos_val.abs().min(neg_val.abs())
                        / pos_val.abs().max(neg_val.abs());
                    let confidence = amplitude_ratio * 0.8 + 0.2; // 0.2 base

                    candidates.push(DipoleCandidate {
                        center: (
                            (max_pos.0 + min_pos.0) / 2,
                            (max_pos.1 + min_pos.1) / 2,
                        ),
                        positive_peak: pos_val,
                        negative_peak: neg_val,
                        separation,
                        separation_meters,
                        confidence,
                        direction,
                    });
                }
            }
        }

        // Sort by confidence (highest first)
        candidates.sort_by(|a, b| b.confidence.partial_cmp(&a.confidence).unwrap_or(std::cmp::Ordering::Equal));
        candidates
    }
}

/// Classify a dipole candidate based on aspect ratio and characteristics.
pub fn classify_target(
    candidate: &DipoleCandidate,
    horizontal_energy: f64,
    vertical_energy: f64,
) -> TargetType {
    // Galvanic cell: weak but persistent, high symmetry
    if candidate.confidence > 0.8
        && candidate.positive_peak.abs() < 10.0 // Weak signal (nT)
        && candidate.separation_meters < 50.0
    {
        return TargetType::GalvanicDipole;
    }

    // Aspect ratio classification
    if horizontal_energy > vertical_energy * 2.0 {
        TargetType::ElongatedHorizontal // Likely a wreck
    } else if vertical_energy > horizontal_energy * 2.0 {
        TargetType::VerticalStructure // Likely wellhead/pipes
    } else {
        TargetType::UnknownBlob
    }
}

// --- FFT Implementation (simplified, f64 precision) ---

#[derive(Debug, Clone, Copy)]
struct Complex {
    re: f64,
    im: f64,
}

impl Complex {
    fn new(re: f64, im: f64) -> Self { Self { re, im } }
    fn zero() -> Self { Self { re: 0.0, im: 0.0 } }
    fn mul(self, other: Self) -> Self {
        Complex {
            re: self.re * other.re - self.im * other.im,
            im: self.re * other.im + self.im * other.re,
        }
    }
    fn add(self, other: Self) -> Self {
        Complex { re: self.re + other.re, im: self.im + other.im }
    }
}

/// 2D FFT via row-then-column 1D FFTs.
fn fft_2d(data: &[f64], rows: usize, cols: usize) -> Vec<Complex> {
    let mut result: Vec<Complex> = data.iter().map(|&v| Complex::new(v, 0.0)).collect();

    // FFT each row
    for row in 0..rows {
        let start = row * cols;
        let row_data: Vec<Complex> = result[start..start + cols].to_vec();
        let fft_row = fft_1d(&row_data, false);
        result[start..start + cols].copy_from_slice(&fft_row);
    }

    // FFT each column
    for col in 0..cols {
        let col_data: Vec<Complex> = (0..rows).map(|row| result[row * cols + col]).collect();
        let fft_col = fft_1d(&col_data, false);
        for row in 0..rows {
            result[row * cols + col] = fft_col[row];
        }
    }

    result
}

/// Inverse 2D FFT.
fn ifft_2d(data: &[Complex], rows: usize, cols: usize) -> Vec<f64> {
    let mut result = data.to_vec();
    let n = (rows * cols) as f64;

    // IFFT each row
    for row in 0..rows {
        let start = row * cols;
        let row_data: Vec<Complex> = result[start..start + cols].to_vec();
        let ifft_row = fft_1d(&row_data, true);
        result[start..start + cols].copy_from_slice(&ifft_row);
    }

    // IFFT each column
    for col in 0..cols {
        let col_data: Vec<Complex> = (0..rows).map(|row| result[row * cols + col]).collect();
        let ifft_col = fft_1d(&col_data, true);
        for row in 0..rows {
            result[row * cols + col] = ifft_col[row];
        }
    }

    // Extract real parts and normalize
    result.iter().map(|c| c.re / n).collect()
}

/// Cooley-Tukey radix-2 FFT (or DFT for non-power-of-2).
fn fft_1d(input: &[Complex], inverse: bool) -> Vec<Complex> {
    let n = input.len();
    if n <= 1 {
        return input.to_vec();
    }

    // DFT for non-power-of-2 (slower but correct)
    if n & (n - 1) != 0 {
        return dft(input, inverse);
    }

    // Radix-2 FFT
    let even: Vec<Complex> = input.iter().step_by(2).cloned().collect();
    let odd: Vec<Complex> = input.iter().skip(1).step_by(2).cloned().collect();

    let even_fft = fft_1d(&even, inverse);
    let odd_fft = fft_1d(&odd, inverse);

    let sign = if inverse { 1.0 } else { -1.0 };
    let mut result = vec![Complex::zero(); n];

    for k in 0..n / 2 {
        let angle = sign * 2.0 * PI * k as f64 / n as f64;
        let twiddle = Complex::new(angle.cos(), angle.sin());
        let t = twiddle.mul(odd_fft[k]);
        result[k] = even_fft[k].add(t);
        result[k + n / 2] = Complex {
            re: even_fft[k].re - t.re,
            im: even_fft[k].im - t.im,
        };
    }

    result
}

/// Direct DFT for non-power-of-2 sizes.
fn dft(input: &[Complex], inverse: bool) -> Vec<Complex> {
    let n = input.len();
    let sign = if inverse { 1.0 } else { -1.0 };
    let mut result = vec![Complex::zero(); n];

    for k in 0..n {
        for j in 0..n {
            let angle = sign * 2.0 * PI * (k * j) as f64 / n as f64;
            let twiddle = Complex::new(angle.cos(), angle.sin());
            result[k] = result[k].add(twiddle.mul(input[j]));
        }
    }

    result
}

/// Butterworth bandpass gain function.
fn bandpass_gain(freq: f64, low: f64, high: f64, width: f64) -> f64 {
    let order = 4.0; // 4th order Butterworth
    let low_gain = 1.0 / (1.0 + (low / (freq + 1e-10)).powf(2.0 * order));
    let high_gain = 1.0 / (1.0 + (freq / high).powf(2.0 * order));
    low_gain * high_gain
}

/// Compute detection threshold as N standard deviations above mean.
fn compute_threshold(data: &[f64], n_sigma: f64) -> f64 {
    let n = data.len() as f64;
    let mean: f64 = data.iter().sum::<f64>() / n;
    let variance: f64 = data.iter().map(|&x| (x - mean).powi(2)).sum::<f64>() / n;
    let std_dev = variance.sqrt();
    mean + n_sigma * std_dev
}

/// Find local extrema (maxima or minima) above threshold.
fn find_local_extrema(
    data: &[f64],
    rows: usize,
    cols: usize,
    find_maxima: bool,
    threshold: f64,
) -> Vec<(usize, usize)> {
    let mut extrema = Vec::new();

    for row in 1..rows - 1 {
        for col in 1..cols - 1 {
            let val = data[row * cols + col];

            // Check threshold
            if find_maxima && val < threshold {
                continue;
            }
            if !find_maxima && val > threshold {
                continue;
            }

            // Check if local extremum (compare to 8 neighbors)
            let mut is_extremum = true;
            for dr in -1i32..=1 {
                for dc in -1i32..=1 {
                    if dr == 0 && dc == 0 {
                        continue;
                    }
                    let nr = (row as i32 + dr) as usize;
                    let nc = (col as i32 + dc) as usize;
                    let neighbor = data[nr * cols + nc];

                    if find_maxima && neighbor > val {
                        is_extremum = false;
                        break;
                    }
                    if !find_maxima && neighbor < val {
                        is_extremum = false;
                        break;
                    }
                }
                if !is_extremum {
                    break;
                }
            }

            if is_extremum {
                extrema.push((row, col));
            }
        }
    }

    extrema
}
