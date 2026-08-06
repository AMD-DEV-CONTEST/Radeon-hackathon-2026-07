from __future__ import annotations

import sys

import export_keep_unpostable_video_v1 as base


base.OUTPUT = base.ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-video-v2"
base.VIDEO_FILENAME = "keep-the-unpostable-vertical-4k-v2.mp4"
base.RECEIPT_SCHEMA = "ProofLaunchKeepUnpostableVideoReceiptV2"
base.CREATIVE_VERSION = "v2-immediate-release-challenger"
base.STORY_BEATS = ["memory gap", "one useless detail", "make it unpostable", "delete if meaningless"]
base.SCENES = (
    {
        "id": "01",
        "theme": "paper",
        "eyebrow": "0:00 / OPEN THE MEMORY GAP",
        "headline": "NAME LAST<br>TUESDAY.",
        "body": "Your camera roll saved the evidence. Did it save what the day felt like?",
        "motif": '<div class="note">TUE / THE TRAIN ARRIVED EARLY.</div><div class="ring"></div>',
        "footer": "YOUR DAY DOES NOT NEED A DOCUMENTARY",
    },
    {
        "id": "02",
        "theme": "blue",
        "eyebrow": "0:03 / STEAL ONE DETAIL",
        "headline": "KEEP ONE<br>USELESS<br>THING.",
        "body": "THE WRONG SONG · THE BLUE CUP · THE SENTENCE YOU ALMOST LOST",
        "motif": '<div class="tiles"><span>WRONG SONG</span><span>BLUE CUP</span><span>HALF SENTENCE</span><span>LAST TRAIN</span></div>',
        "footer": "USELESS TO THE FEED · USEFUL TO YOU",
    },
    {
        "id": "03",
        "theme": "ink",
        "eyebrow": "0:07 / REMOVE THE PERFORMANCE",
        "headline": "MAKE IT<br>UNPOSTABLE.",
        "body": "IF IT NEEDS AN AUDIENCE, IT ISN’T YOURS YET.",
        "motif": '<div class="private-card"><i>DAY 07</i><b>PRIVATE MEMORY</b><span>NO REVEAL REQUIRED</span></div>',
        "footer": "THE MEMORY STAYS FACE-DOWN UNTIL YOU CHOOSE",
    },
    {
        "id": "04",
        "theme": "yellow",
        "eyebrow": "0:11 / MAKE IT EARN THE HABIT",
        "headline": "DELETE IT<br>IF IT MEANT<br>NOTHING.",
        "body": "KEEP · EDIT · EXPORT · DELETE",
        "motif": '<div class="reply">REPLY ONLY <b>KEEP</b><br><small>NOT THE MEMORY.</small></div>',
        "footer": "NO STREAK · NO AUDIENCE · NO CATCH-UP QUEST",
    },
)


if __name__ == "__main__":
    sys.argv[0] = "export_keep_unpostable_video_v2.py"
    base.main()
