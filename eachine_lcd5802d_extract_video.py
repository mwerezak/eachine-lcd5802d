from __future__ import annotations

import os
import re
import subprocess
from tempfile import TemporaryDirectory
from argparse import ArgumentParser
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from typing import Optional


FFMPEG_PATH = R'ffmpeg.exe'

COMPRESSION_PRESETS = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow']

class VideoCodec(Enum):
	H264 = ('libx264', 22)
	H265 = ('libx265', 28)

	@property
	def codec(self) -> str:
		return self.value[0]

	@property
	def default_crf(self) -> int:
		return self.value[1]
	

class AudioCodec(Enum):
	AAC = 'aac'
	AC3 = 'ac3'

	@property
	def codec(self) -> str:
		return self.value

cli = ArgumentParser(
	description="Process recorded DVR footage from Eachine LCD5802D FPV receiver."
)

cli.add_argument(
	'source_path',
	help = "Filesystem path to a location CONTAINING the DCIM folder where the DVR recordings are stored.",
	metavar = "INPUT",
)
cli.add_argument(
	'input_range',
	help = "The range of recorded entries to include in the output file",
	metavar = "START:END",
)
cli.add_argument(
	'output',
	help = "Where to write the output file.",
	metavar = "OUTPUT"
)
cli.add_argument(
	'--ffmpeg-path',
	default = FFMPEG_PATH,
	help = "Path to ffmpeg executable.",
	metavar = "PATH",
	dest = 'ffmpeg_path',
)
# cli.add_argument(
# 	'-L', '--compression-level',
# 	type = int,
# 	default = None,
# 	help = "Compression level. Defaults to 22 for h.264 and 28 for h.265.",
# 	metavar = "LEVEL",
# 	dest = 'compression',
# )
# cli.add_argument(
# 	'--compression-preset',
# 	default = 'medium',
# 	choices = COMPRESSION_PRESETS,
# 	help = (
# 		"The preset determines compression efficiency and therefore affects encoding speed. "
# 		"Valid presets are 'ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', and 'veryslow'. "
# 		"Use the slowest preset you have patience for."
# 	),
# 	metavar = "PRESET",
# 	dest = 'preset',
# )
# cli.add_argument(
# 	'--video-codec',
# 	default = VideoCodec.H265.name.casefold(),
# 	type = lambda s: s.casefold(),
# 	choices = list(codec.name.casefold() for codec in VideoCodec),
# 	help = "The video codec to use.",
# 	metavar = "CODEC",
# 	dest = 'video_codec',
# )
# cli.add_argument(
# 	'--audio-codec',
# 	default = AudioCodec.AAC.name.casefold(),
# 	type = lambda s: s.casefold(),
# 	choices = list(codec.name.casefold() for codec in AudioCodec),
# 	help = "The audio codec to use.",
# 	metavar = "CODEC",
# 	dest = 'audio_codec',
# )
# cli.add_argument(
# 	'-C', '--compat-mode',
# 	action = 'store_true',
# 	help = "Force compatiblity settings for video encoding.",
# 	dest = 'compatibility_mode',
)

def dvr_filename(index: int) -> str:
	return f'PICT{index:04d}.AVI'

_filename_pat = re.compile(r'PICT(?P<index>\d+).AVI', flags=re.IGNORECASE)
def find_input_files(source_path: str) -> dict[int, str]:
	"""Verifies that `source_path` contains the correct DCIM folder
	and returns a list of all input file paths"""

	if not os.path.exists(source_path):
		raise ValueError(f"'{source_path}' folder not found")
	if not os.path.isdir(source_path):
		raise ValueError(f"'{source_path}' is not a directory")

	dcim_path = os.path.join(source_path, 'DCIM')
	if not os.path.exists(dcim_path) or not os.path.isdir(dcim_path):
		raise ValueError("'DCIM' folder not found")

	input_path = os.path.join(dcim_path, '100DSCIM')
	if not os.path.exists(input_path) or not os.path.isdir(input_path):
		raise ValueError("'100DSCIM' folder not found")

	return {
		int(match.groupdict()['index']) : path
		for filename in os.listdir(input_path)
		if os.path.isfile(path := os.path.join(input_path, filename))
		if (match := _filename_pat.fullmatch(filename)) is not None
	}

def parse_range(s: str) -> tuple[Optional[int], Optional[int]]:
	parts = s.split(':', 2)
	if len(parts) != 2:
		raise ValueError("invalid range")
	start, end = parts

	start = start.strip()
	if start == '':
		start = None
	else:
		try:
			start = int(start)
		except ValueError:
			raise ValueError("invalid start index") from None

	end = end.strip()
	if end == '':
		end = None
	else:
		try:
			end = int(end)
		except ValueError:
			raise ValueError("invalid end index") from None

	return start, end

def join_and_compress_videos(
		ffmpeg_path: str, 
		input_paths: list[str], 
		output_path: str, 
		*, 
		compression: Optional[int] = None, 
		preset: str = 'faster', 
		video_codec: VideoCodec = VideoCodec.H265, 
		audio_codec: AudioCodec = AudioCodec.AAC,
		compatibility_mode: bool = False,
	) -> None:

	if compression is None:
		compression = video_codec.default_crf

	with TemporaryDirectory() as tempdir:
		# pad audio to avoid desync with video
		#ffmpeg -i segment1.mov -af apad -c:v copy <audio encoding params> -shortest -avoid_negative_ts make_zero -fflags +genpts padded1.mo
		segment_paths = []
		for idx, input_path in enumerate(input_paths):
			segment_path = os.path.join(tempdir, f'segment{idx:03d}.avi')
			segment_paths.append(segment_path)

			pad_cmd = [
				ffmpeg_path, '-y', '-i', input_path, '-af', 'apad', '-c:v', 'copy', '-c:a', audio_codec.value, 
				'-shortest', '-avoid_negative_ts', 'make_zero', '-fflags', '+genpts', segment_path,
			]
			subprocess.run(pad_cmd, check=True)

		manifest_path = os.path.join(tempdir, 'concat.txt')
		with open(manifest_path, 'wt') as f:
			for path in segment_paths:
				f.write(f"file '{path}'\r\n")

		temp_path = os.path.join(tempdir, 'concat.avi')

		concat_cmd = [
			ffmpeg_path, '-y', '-f', 'concat', '-safe', '0', '-i', manifest_path, '-c', 'copy', temp_path,
		]
		subprocess.run(concat_cmd, check=True)

		extra_encode_args = ()
		if compatibility_mode:
			video_codec = VideoCodec.H264
			extra_encode_args = ['-profile:v', 'baseline', '-level', '3.0', '-pix_fmt', 'yuv420p']
			#-c:v libx264 -profile:v baseline -level 3.0 -pix_fmt yuv420p

		encode_cmd = [
			ffmpeg_path, '-y', '-i', temp_path, 
			'-c:a', 'copy',
			'-c:v', video_codec.value,
			*extra_encode_args,
			'-crf', str(compression), 
			'-preset', preset, 
			output_path,
		]
		subprocess.run(encode_cmd, check=True)


# def join_and_compress_avi(
# 		ffmpeg_path: str, input_paths: list[str], output_path: str, *, 
# 		compression: Optional[int] = None, 
# 		preset: str = 'faster', 
# 		video_codec: VideoCodec = VideoCodec.H265, 
# 		audio_codec: AudioCodec = AudioCodec.AAC,
# 		compatibility_mode: bool = False,
# 	) -> None:
	
# 	if compression is None:
# 		compression = video_codec.default_crf

# 	extra_encode_args = ()
# 	if compatibility_mode:
# 		video_codec = VideoCodec.H264
# 		extra_encode_args = ['-profile:v', 'baseline', '-level', '3.0', '-pix_fmt', 'yuv420p']
# 		#-c:v libx264 -profile:v baseline -level 3.0 -pix_fmt yuv420p


# 	with TemporaryDirectory() as tempdir:
# 		segment_paths = []
# 		for idx, input_path in enumerate(input_paths):
# 			segment_path = os.path.abspath(os.path.join(tempdir, f'segment{idx:d}.avi'))
# 			segment_paths.append(segment_path)

# 			encode_cmd = [
# 				ffmpeg_path, '-y', '-i', input_path, '-af', 'apad',
# 				'-c:a', audio_codec.codec, '-shortest', '-avoid_negative_ts', 'make_zero', '-fflags', '+genpts',  # pad audio to avoid desync with video
# 				'-c:v', video_codec.codec, *extra_encode_args, '-crf', str(compression), '-preset', preset,
# 				segment_path,
# 			]
# 			subprocess.run(encode_cmd, check=True)

# 		manifest_path = os.path.join(tempdir, 'concat.txt')
# 		with open(manifest_path, 'wt') as f:
# 			for path in segment_paths:
# 				f.write(f"file '{path}'\r\n")

# 		concat_cmd = [
# 			ffmpeg_path, '-y', '-f', 'concat', '-safe', '0', '-i', manifest_path, '-c', 'copy', output_path,
# 		]
# 		subprocess.run(concat_cmd, check=True)

if __name__ == '__main__':
	import sys

	args = cli.parse_args()

	if os.path.exists(args.output):
		print(f"Output file '{args.output}' already exists!")
		sys.exit()

	try:
		video_files = find_input_files(args.source_path)
	except ValueError as err:
		print(f"Could not locate video files: {err}")
		sys.exit()

	if len(video_files) == 0:
		print(f"No DVR recordings.")
		sys.exit()

	try:
		start, end = parse_range(args.input_range)
	except ValueError:
		print(f"Invalid range '{args.input_range}'")
		sys.exit()

	if start is None:
		start = min(video_files.keys())
	if end is None:
		end = max(video_files.keys())

	missing = [
		idx for idx in range(start, end+1) if idx not in video_files.keys()
	]
	if len(missing) > 0:
		print(f"Could not find all video files in range '{args.input_range}'. Missing files:")
		for idx in missing:
			print(dvr_filename(idx))
		sys.exit()

	vcodecs = { codec.name.casefold() : codec for codec in VideoCodec }
	acodecs = { codec.name.casefold() : codec for codec in AudioCodec }

	input_files = [ video_files[idx] for idx in range(start, end+1) ]
	join_and_compress_avi(
		args.ffmpeg_path, input_files, args.output, 
		compression = args.compression,
		preset = args.preset,
		video_codec = vcodecs[args.video_codec],
		audio_codec = acodecs[args.audio_codec],
		compatibility_mode = args.compatibility_mode,
	)
