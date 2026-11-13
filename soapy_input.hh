// Copyright (c) 2026 Mike Brown
// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef VDL2_SNIFFER_SOAPY_INPUT_HH
#define VDL2_SNIFFER_SOAPY_INPUT_HH

#include <atomic>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace SoapySDR { class Device; class Stream; }
class RateConverter;

// A radio through SoapySDR (HackRF, Airspy R2, Airspy HF+, an RTL-SDR, ...).
//
// Its reader thread brings the samples to the decoder's own rate and tuning
// (1.05 MS/s centred on the channel plan) with the RateConverter and hands
// them to the main loop as ci16 through a pipe, so the main loop sees what a
// 1.05 MS/s recording would give it, and the conversion runs on its own core.
// A radio that can produce 1.05 MS/s on the plan's centre itself (an RTL-SDR)
// is passed through untouched.
//
// As with RtlInput, a block the pipe has no room for is dropped whole and
// counted rather than written late. Samples the radio itself lost (an
// overflow) are counted from the clock: after an overflow, the shortfall of
// samples delivered against the time since the first one.
struct SoapyOptions {
    std::string args;          // "driver=hackrf", "driver=airspy,serial=...", "" = the first radio
    std::string gain = "auto"; // auto | dB | NAME=dB,NAME=dB
    std::string antenna;       // "" = the driver's default
    double rate = 0;           // radio rate; 0 = choose
    double centre = 0;         // radio centre; 0 = choose
    int ppm = 0;
    bool biasTee = false;
    std::vector<std::pair<std::string, std::string>> settings;   // --soapy-setting KEY=VALUE
};

class SoapyInput {
public:
    std::atomic<uint64_t> dropped{0};   // output bytes (ci16 at outRate) not delivered
    std::atomic<uint64_t> arrived{0};   // radio samples delivered by the driver
    std::atomic<uint64_t> overflows{0};
    std::atomic<bool> failed{false};    // the radio stopped without being asked
    std::string device, tuner, gain;    // for the live page
    double rate = 0, centre = 0;        // what the radio was set to

    // channels and planCentre: the decoder's; outRate its rate. stop: set when
    // the process is asked to end. Returns the read end of the pipe (ci16 at
    // outRate centred on planCentre), or null with the reason on stderr.
    FILE* open(const SoapyOptions& o, const std::vector<double>& channels, double planCentre, double outRate,
               const volatile sig_atomic_t* stop);
    void stop();
    ~SoapyInput();

private:
    void run();
    void put(const void* data, size_t bytes);

    SoapySDR::Device* dev_ = nullptr;
    SoapySDR::Stream* stream_ = nullptr;
    std::unique_ptr<RateConverter> rs_;
    double outRate_ = 0;
    int fd_[2] = {-1, -1};
    int pipeSize_ = 0;
    std::thread th_;
    std::atomic<bool> cancelled_{false};
    const volatile sig_atomic_t* stop_ = nullptr;
    SoapyOptions o_;
};

// For --help: the radios SoapySDR can see, one per line.
void soapyList(FILE* out);

#endif
