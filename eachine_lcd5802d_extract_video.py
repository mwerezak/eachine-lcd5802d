from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from tempfile import TemporaryDirectory
from argparse import ArgumentParser
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from typing import Optional


FFMPEG_PATH = R'ffmpeg'

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
	help = "Path to the FFmpeg executable.",
	metavar = "PATH",
	dest = 'ffmpeg_path',
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

class VideoProcessor:
	def __init__(self, ffmpeg_path: str):
		self._ffmpeg = ffmpeg_path

	def _convert_segments(self, input_paths: list[str], output_path: str) -> list[str]:
		segment_paths = []
		for idx, input_path in enumerate(input_paths):
			segment_path = os.path.join(output_path, f'segment{idx:03d}.mkv')
			segment_paths.append(segment_path)

			segment_cmd = [
				self._ffmpeg, '-y', 
				'-i', input_path,
				'-threads', '8',
				'-acodec', 'copy',  # it's already PCM
				#'-acodec', 'pcm_s16le', '-ac', '1', '-ar', '8000',
				'-vcodec', 'ffv1', '-level', '3', '-coder', '1', '-context', '1', '-g', '1', '-slices', '24', '-slicecrc', '1',
				'-t', '5:00',
				segment_path,
			]
			subprocess.run(segment_cmd, check=True)
		return segment_paths

	def _concat_segments(self, input_paths: list[str], output_path: str) -> None:
		with TemporaryDirectory() as tempdir:
			manifest_path = os.path.join(tempdir, 'concat.txt')
			with open(manifest_path, 'wt') as f:
				for path in input_paths:
					f.write(f"file '{path}'\r\n")

			concat_cmd = [
				self._ffmpeg, '-y',
				'-f', 'concat', '-safe', '0', '-i', manifest_path,
				'-acodec', 'copy',
				'-vcodec', 'copy',
				'-max_interleave_delta', '0',
				output_path,
			]
			subprocess.run(concat_cmd, check=True)

	def _encode_output(self, input_path: str, output_path: str) -> None:
		encode_cmd = [
			self._ffmpeg, '-y', '-i', input_path,
			'-acodec', 'aac', '-aq', '1', '-ac', '1', '-ar', '8000',
			'-vcodec', 'libx264', '-preset', 'medium', '-crf', '23', '-vprofile', 'high422', '-g', '150', '-bf', '3', '-pix_fmt', 'yuv420p',
			'-movflags', '+faststart',
			output_path,
		]
		subprocess.run(encode_cmd, check=True)

	def join_and_compress_video(self, input_paths: list[str], output_path: str) -> None:
		with TemporaryDirectory() as tempdir:
			segment_paths = self._convert_segments(input_paths, tempdir)

			temp_path = os.path.join(tempdir, 'concat.mkv')
			self._concat_segments(segment_paths, temp_path)

			self._encode_output(temp_path, output_path)


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

	input_files = [ video_files[idx] for idx in range(start, end+1) ]

	print('*** Eachine LCD5802D Video Extractor ***')
	print(f"FFMPEG path:\n  '{args.ffmpeg_path}'")
	print(f"Input:" + ''.join(f"\n  '{path}'" for path in input_files))
	print(f"Output:\n  '{args.output}'")

	start_time = datetime.now()
	VideoProcessor(args.ffmpeg_path).join_and_compress_video(input_files, args.output)
	elapsed = datetime.now() - start_time

	print(f"Finished processing in {elapsed}")
