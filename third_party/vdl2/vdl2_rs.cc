#include "vdl2_rs.hh"

#include <algorithm>

namespace Jetstream::Vdl2Receiver {

namespace {
constexpr int PRIM = 0x187;
constexpr int FCR = 120;          // first consecutive root exponent
}  // namespace

ReedSolomon::ReedSolomon() {
    int x = 1;
    for (int i = 0; i < 255; ++i) {
        exp_[i] = static_cast<std::uint8_t>(x);
        log_[x] = static_cast<std::uint8_t>(i);
        x <<= 1;
        if (x & 0x100) x ^= PRIM;
    }
    for (int i = 255; i < 512; ++i) exp_[i] = exp_[i - 255];
    log_[0] = 0;
}

std::uint8_t ReedSolomon::mul(std::uint8_t a, std::uint8_t b) const {
    if (!a || !b) return 0;
    return exp_[log_[a] + log_[b]];
}
std::uint8_t ReedSolomon::div(std::uint8_t a, std::uint8_t b) const {
    if (!a) return 0;
    return exp_[(log_[a] - log_[b] + 255) % 255];
}
std::uint8_t ReedSolomon::inv(std::uint8_t a) const {
    return exp_[(255 - log_[a]) % 255];
}
std::uint8_t ReedSolomon::pow(std::uint8_t a, int n) const {
    if (!a) return 0;
    int e = (static_cast<int>(log_[a]) * n) % 255;
    if (e < 0) e += 255;
    return exp_[e];
}

std::vector<std::uint8_t> ReedSolomon::polyMul(const std::vector<std::uint8_t>& p,
                                               const std::vector<std::uint8_t>& q) const {
    std::vector<std::uint8_t> r(p.size() + q.size() - 1, 0);
    for (std::size_t j = 0; j < q.size(); ++j) {
        if (!q[j]) continue;
        for (std::size_t i = 0; i < p.size(); ++i) {
            if (p[i]) r[i + j] ^= mul(p[i], q[j]);
        }
    }
    return r;
}

std::uint8_t ReedSolomon::polyEval(const std::vector<std::uint8_t>& p, std::uint8_t x) const {
    std::uint8_t y = p.empty() ? 0 : p[0];
    for (std::size_t i = 1; i < p.size(); ++i) y = static_cast<std::uint8_t>(mul(y, x) ^ p[i]);
    return y;
}

std::vector<std::uint8_t> ReedSolomon::syndromes(const std::vector<std::uint8_t>& cw) const {
    std::vector<std::uint8_t> s(Parity + 1, 0);   // leading zero, as the loop below indexes from 1
    for (int i = 0; i < Parity; ++i) {
        s[i + 1] = polyEval(cw, exp_[(i + FCR) % 255]);
    }
    return s;
}

void ReedSolomon::encode(std::vector<std::uint8_t>& cw) const {
    if (static_cast<int>(cw.size()) != BlockTotal) return;

    // Generator: the product of (x - alpha^i) over the six roots. The
    // codeword is stored most significant first, so the message occupies
    // positions 0..248 and the remainder lands in the last six.
    std::vector<std::uint8_t> gen{1};
    for (int i = 0; i < Parity; ++i) {
        gen = polyMul(gen, {1, exp_[(i + FCR) % 255]});
    }

    std::vector<std::uint8_t> work(cw.begin(), cw.begin() + BlockData);
    work.resize(BlockTotal, 0);
    for (int i = 0; i < BlockData; ++i) {
        const std::uint8_t coef = work[i];
        if (!coef) continue;
        for (std::size_t j = 1; j < gen.size(); ++j) {
            work[i + j] ^= mul(gen[j], coef);
        }
    }
    for (int i = 0; i < Parity; ++i) {
        cw[BlockData + i] = work[BlockData + i];
    }
}

bool ReedSolomon::clean(const std::vector<std::uint8_t>& cw) const {
    const auto s = syndromes(cw);
    return std::all_of(s.begin(), s.end(), [](std::uint8_t v) { return v == 0; });
}

int ReedSolomon::correct(std::vector<std::uint8_t>& cw,
                         const std::vector<int>& erasures) const {
    if (static_cast<int>(erasures.size()) > Parity) return -1;
    auto synd = syndromes(cw);
    if (std::all_of(synd.begin(), synd.end(), [](std::uint8_t v) { return v == 0; })) {
        return 0;
    }

    // Divide out the known erasure positions so Berlekamp-Massey only has
    // to account for whatever errors remain.
    std::vector<std::uint8_t> work(synd.begin() + 1, synd.end());
    for (int p : erasures) {
        const std::uint8_t xp = exp_[(cw.size() - 1 - p) % 255];
        for (std::size_t j = 0; j + 1 < work.size(); ++j) {
            work[j] = static_cast<std::uint8_t>(mul(work[j], xp) ^ work[j + 1]);
        }
    }

    const std::vector<std::uint8_t>& bm = erasures.empty() ? synd : work;
    const int shift = erasures.empty() ? static_cast<int>(synd.size()) - Parity : 0;
    const int rounds = Parity - static_cast<int>(erasures.size());

    std::vector<std::uint8_t> errLoc{1}, oldLoc{1};
    for (int i = 0; i < rounds; ++i) {
        const int K = i + shift;
        std::uint8_t delta = bm[K];
        for (std::size_t j = 1; j < errLoc.size(); ++j) {
            delta ^= mul(errLoc[errLoc.size() - 1 - j], bm[K - j]);
        }
        oldLoc.push_back(0);
        if (delta) {
            if (oldLoc.size() > errLoc.size()) {
                std::vector<std::uint8_t> scaled;
                for (auto c : oldLoc) scaled.push_back(mul(c, delta));
                std::vector<std::uint8_t> back;
                for (auto c : errLoc) back.push_back(mul(c, inv(delta)));
                oldLoc = back;
                errLoc = scaled;
            }
            std::vector<std::uint8_t> scaled;
            for (auto c : oldLoc) scaled.push_back(mul(c, delta));
            std::vector<std::uint8_t> sum(std::max(errLoc.size(), scaled.size()), 0);
            for (std::size_t k = 0; k < errLoc.size(); ++k) sum[k + sum.size() - errLoc.size()] = errLoc[k];
            for (std::size_t k = 0; k < scaled.size(); ++k) sum[k + sum.size() - scaled.size()] ^= scaled[k];
            errLoc = sum;
        }
    }
    while (!errLoc.empty() && errLoc.front() == 0) errLoc.erase(errLoc.begin());
    std::reverse(errLoc.begin(), errLoc.end());

    const int nerr = static_cast<int>(errLoc.size()) - 1;
    std::vector<int> errPos;
    for (std::size_t i = 0; i < cw.size(); ++i) {
        if (polyEval(errLoc, exp_[i % 255]) == 0) {
            errPos.push_back(static_cast<int>(cw.size() - 1 - i));
        }
    }
    if (static_cast<int>(errPos.size()) != nerr) return -1;
    if (2 * nerr + static_cast<int>(erasures.size()) > Parity) return -1;

    std::vector<int> all = erasures;
    all.insert(all.end(), errPos.begin(), errPos.end());

    // Errata locator from the known positions, so its derivative comes out
    // as a product rather than formally.
    std::vector<int> coefPos;
    for (int p : all) coefPos.push_back(static_cast<int>(cw.size()) - 1 - p);
    std::vector<std::uint8_t> eLoc{1};
    for (int c : coefPos) eLoc = polyMul(eLoc, {pow(2, c), 1});

    std::vector<std::uint8_t> syndRev(synd.rbegin(), synd.rend());
    auto prod = polyMul(syndRev, eLoc);
    const int keep = static_cast<int>(eLoc.size());
    std::vector<std::uint8_t> eEval(prod.end() - keep, prod.end());
    std::reverse(eEval.begin(), eEval.end());

    for (std::size_t i = 0; i < all.size(); ++i) {
        const std::uint8_t Xi = pow(2, coefPos[i] % 255);
        const std::uint8_t XiInv = inv(Xi);
        std::uint8_t prime = 1;
        for (std::size_t j = 0; j < all.size(); ++j) {
            if (j != i) prime = mul(prime, static_cast<std::uint8_t>(1 ^ mul(XiInv, pow(2, coefPos[j] % 255))));
        }
        if (!prime) return -1;
        std::vector<std::uint8_t> rev(eEval.rbegin(), eEval.rend());
        std::uint8_t y = polyEval(rev, XiInv);
        y = mul(y, pow(Xi, 1 - FCR));
        cw[all[i]] ^= div(y, prime);
    }
    return clean(cw) ? nerr : -1;
}

}  // namespace Jetstream::Vdl2Receiver
