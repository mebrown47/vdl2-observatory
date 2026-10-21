# VDL Mode 2 receiver (vendored)

From CyberEther (Luigi F. Cruz, MIT; `LICENSE`), `src/domains/dsp/vdl2/` at commit `9905d4fe`:
`vdl2_decoder`, `vdl2_rs`, `vdl2_acars`. A clean-room implementation written from ETSI EN 301
841-1 and measurements on the air, with dumpvdl2 used only as a black-box oracle. Copied
from iridium-analyzer's `third_party/vdl2`, which carries the first two changes below.

Changes marked `(iridium-analyzer)` in the source:
- `vdl2_acars.cc` does not include CyberEther's `jetstream/config.hh`; the build defines
  `JETSTREAM_LOADER_LIBACARS_AVAILABLE` when libacars-2 is there.
- `Frame::burstFirst` / `burstLast` and `Decoder::ringSampleToInput`: where each frame's burst
  was, so a frame can be timed to the sample.

Changes marked `(vdl2-sniffer)` in the source:
- `AcarsContent::treeJson`: libacars's JSON for the whole tree, for the archive and the
  dumpvdl2-style output.
- `AcarsContent::messageText`: the text as libacars reads it, sub-label prefix removed.
- **Any number of Reed-Solomon blocks.** Upstream decodes one full block plus a short one and
  corrects only the first; frames over 498 octets were lost. Now every block is a row, the
  stream is the data read column-wise and then the parity read column-wise, and every block is
  corrected. On one and two blocks this is the layout measured before.
- **Parity octets by block length** (`ShortBlockParity`): <= 30 octets carry 2, up to 67 carry 4,
  and longer carry 6. Upstream used 6 for everything over 30, so frames of 31-67 octets
  (mostly ACARS) spent two of their corrections on parity that was never sent. Measured on a
  550-octet feeder frame (56-octet last block: zero corrections with 4, 6 with 2, 4 with 6),
  and on ~140 single-block frames: 44-66 octets show the 4-parity signature, 73 and up do not.
  The limits at 30 and 67 sit in unobserved gaps (31-43, 67-72).

Keep in step with CyberEther by copying the files again
and re-applying the marked changes. The last two are worth sending upstream.
