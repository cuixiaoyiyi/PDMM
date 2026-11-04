# Source and dependency notices

The current implementation is in `src/rev`, `src/rev8`, and `src/shadow`. The shadow classes modify FlowDroid 2.15.1 entry-point and callback construction. Their upstream source is https://github.com/secure-software-engineering/FlowDroid/tree/v2.15.1; its licence text is preserved in `third_party/FlowDroid-LICENSE.txt`.

DMMPP and Androlic dependency files come from https://github.com/cuixiaoyiyi/DMMPP at commit `67585397c564a84295e3bd545b8e6b38438bfff8`. Their JAR contents retain their bundled notices. The dependency downloader preserves the original JAR bytes and verifies recorded SHA-256 hashes.

The DroidBench inventory uses https://github.com/secure-software-engineering/DroidBench at commit `a57fa6f42f278591695672f1aa8b37c275139370`. Obtain those benchmark sources and APKs from that upstream repository. Expanded-corpus packages are identified by version, original F-Droid address, and checksum in `experiments/corpus94.csv`.

Earlier repository material is retained in `legacy`. Third-party files keep their original copyright and licence terms.
