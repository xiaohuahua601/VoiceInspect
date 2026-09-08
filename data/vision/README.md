# VoiceInspect vision evaluation set

`manifest.jsonl` is the source of truth. Only entries with a non-null `path` are local evaluation assets. Public references remain pending until the source page and license are re-verified and the image is legally added to the local, non-Git dataset directory.

The current local set contains one project-generated compressor abnormal-case image. It is intentionally not counted as a public-photo score. The release gate requires at least 12 labeled images per device type (normal and abnormal), and a target of 20 per type. Do not copy one image into several device classes or label an unverified photo as abnormal.

Each abnormal case must document visible evidence and uncertainty. Images with no visible anomaly are valuable controls for false-positive measurement.