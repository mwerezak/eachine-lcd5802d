# Eachine LCD5802D Video Extractor

This is a utility to process video files captured by the Eachine LCD5802D FPV monitor's digital video recorder (DVR).

The LCD5802D outputs MJPEG/PCM-encoded AVI files split into 5 minute segments. This is very inconvient for viewing, so I wanted
to be able to join these segments into longer flight videos and re-encode into H.264/AAC.

I found that doing this with FFmpeg was not trivial, getting the video to encode so that the audo wouldn't desync took a few tries. 
Not only that, the solution takes a few encoding passes and is rather cumbersome to do directly in the shell. 
And FFmpeg's concat filter requires creating a temporary file to tell FFmpeg which files to join together. 
All in all, it made sense to roll all of that into a single tool.

## Requirements

This tool uses FFmpeg, and expects `ffmpeg` to be in your path. 
If it is not, you can tell the tool where to find it using the `--ffmpeg-path` command line option.

This is a Python script, so you will need an interpreter. It has been developed and tested with Python 3.11 but I think it should work with Python 3.9+.

## Usage

```
eachine_lcd5802d_extract_video.py INPUT START:END OUTPUT
```

### `INPUT`
You will need to tell the tool the path where it can find the DCIM folder containing the DVR recordings. 
Typically this is the root of the SD card where the video recordings were saved.
So for the `INPUT` parameter you can just put the path to where your SD card is mounted. 
On windows this would be just e.g. `D:\` or whatever.

### `START:END`
On the SD card the LCD5802D stores video recordings with filenames in the form of `PICTnnnn.AVI` where `nnnn` is a number.
Use these numbers to specify which video segments you want to join into a single output video file.

The `START:END` range is **inclusive** so 0:2 would join `PICT0000.AVI`, `PICT0001.AVI`, and `PICT0002.AVI` into a single video.

### `OUTPUT`
The name of the video file to output. 
You can choose whatever file extension you want (.mkv, .mp4, whatever) and I believe that FFmpeg will produce the corresponding container.
Regardless of container the encoding will be H.264/AAC.
