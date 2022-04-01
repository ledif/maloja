import os, datetime, re

import json, csv

from ...cleanup import *
from doreah.io import col, ask, prompt
from ...globalconf import data_dir


c = CleanerAgent()


def warn(msg):
	print(col['orange'](msg))
def err(msg):
	print(col['red'](msg))


def import_scrobbles(inputf):

	if re.match(".*\.csv",inputf):
		type = "Last.fm"
		outputf = data_dir['scrobbles']("lastfmimport.tsv")
		importfunc = parse_lastfm

	elif re.match("endsong_[0-9]+\.json",inputf):
		type = "Spotify"
		outputf = data_dir['scrobbles']("spotifyimport.tsv")
		importfunc = parse_spotify_full

	elif re.match("StreamingHistory[0-9]+\.json",inputf):
		type = "Spotify"
		outputf = data_dir['scrobbles']("spotifyimport.tsv")
		importfunc = parse_spotify_lite

	else:
		print("File",inputf,"could not be identified as a valid import source.")
		return 0,0,0,0


	print(f"Parsing {col['yellow'](inputf)} as {col['cyan'](type)} export")


	if os.path.exists(outputf):
		while True:
			action = prompt(f"Already imported {type} data. [O]verwrite, [A]ppend or [C]ancel?",default='c').lower()[0]
			if action == 'c':
				return 0,0,0,0
			elif action == 'a':
				mode = 'a'
				break
			elif action == 'o':
				mode = 'w'
				break
			else:
				print("Could not understand response.")
	else:
		mode = 'w'


	with open(outputf,mode) as outputfd:
		success, warning, skipped, failed = 0, 0, 0, 0
		timestamps = set()

		for status,scrobble in importfunc(inputf):
			if status == 'FAIL':
				failed += 1
			elif status == 'SKIP':
				skipped += 1
			else:
				success += 1
				if status == 'WARN':
					warning += 1

				while scrobble['timestamp'] in timestamps:
					scrobble['timestamp'] += 1
				timestamps.add(scrobble['timestamp'])

				# Format fields for tsv
				scrobble['timestamp'] = str(scrobble['timestamp'])
				scrobble['duration'] = str(scrobble['duration']) if scrobble['duration'] is not None else '-'
				(artists,scrobble['title']) = c.fullclean(scrobble['artiststr'],scrobble['title'])
				scrobble['artiststr'] = "␟".join(artists)

				outputline = "\t".join([
					scrobble['timestamp'],
					scrobble['artiststr'],
					scrobble['title'],
					scrobble['album'],
					scrobble['duration']
				])
				outputfd.write(outputline + '\n')

				if success % 100 == 0:
					print(f"Imported {success} scrobbles...")

	return success, warning, skipped, failed

def parse_spotify_lite(inputf):
	inputfolder = os.path.dirname(inputf)
	filenames = re.compile(r'StreamingHistory[0-9]+\.json')
	inputfiles = [os.path.join(inputfolder,f) for f in os.listdir(inputfolder) if filenames.match(f)]

	if inputfiles != [inputf]:
		print("Spotify files should all be imported together to identify duplicates across the whole dataset.")
		if not ask("Import " + ", ".join(col['yellow'](i) for i in inputfiles) + "?",default=True):
			inputfiles = [inputf]

	# TODO

def parse_spotify_full(inputf):

	inputfolder = os.path.dirname(inputf)
	filenames = re.compile(r'endsong_[0-9]+\.json')
	inputfiles = [os.path.join(inputfolder,f) for f in os.listdir(inputfolder) if filenames.match(f)]

	if inputfiles != [inputf]:
		print("Spotify files should all be imported together to identify duplicates across the whole dataset.")
		if not ask("Import " + ", ".join(col['yellow'](i) for i in inputfiles) + "?",default=True):
			inputfiles = [inputf]

	# we keep timestamps here as well to remove duplicates because spotify's export
	# is messy - this is specific to this import type and should not be mixed with
	# the outer function timestamp check (which is there to fix duplicate timestamps
	# that are assumed to correspond to actually distinct plays)
	timestamps = {}
	inaccurate_timestamps = {}

	for inputf in inputfiles:

		print("Importing",col['yellow'](inputf),"...")
		with open(inputf,'r') as inputfd:
			data = json.load(inputfd)

		for entry in data:

			try:
				played = int(entry['ms_played'] / 1000)
				timestamp = int(entry['offline_timestamp'] / 1000)
				artist = entry['master_metadata_album_artist_name']
				title = entry['master_metadata_track_name']
				album = entry['master_metadata_album_album_name']


				if title is None:
					warn(f"{entry} has no title, skipping...")
					yield ('SKIP',None)
					continue
				if artist is None:
					warn(f"{entry} has no artist, skipping...")
					yield ('SKIP',None)
					continue
				if played < 30:
					warn(f"{entry} is shorter than 30 seconds, skipping...")
					yield ('SKIP',None)
					continue

				# if offline_timestamp is a proper number, we treat it as
				# accurate and check duplicates by that exact timestamp
				if timestamp != 0:
					status = 'SUCCESS'
					if timestamp in timestamps and (artist,title) in timestamps[timestamp]:
						warn(f"{entry} seems to be a duplicate, skipping...")
						yield ('SKIP',None)
						continue
					timestamps.setdefault(timestamp,[]).append((artist,title))

				# if it's 0, we use ts instead, but identify duplicates much more
				# liberally (cause the ts is not accurate)
				else:
					status = 'WARN'
					warn(f"{entry} might have an inaccurate timestamp.")
					timestamp = int(
						datetime.datetime.strptime(entry['ts'].replace('Z','+0000',),"%Y-%m-%dT%H:%M:%S%z").timestamp()
					)
					# TODO HEURISTICS





				yield (status,{
					'title':title,
					'artiststr': artist,
					'album': album,
				#	'timestamp': int(datetime.datetime.strptime(
				#		entry['ts'].replace('Z','+0000',),
				#		"%Y-%m-%dT%H:%M:%S%z"
				#	).timestamp()),
					'timestamp': timestamp,
					'duration':played
				})
			except Exception as e:
				err(f"{entry} could not be parsed. Scrobble not imported. ({repr(e)})")
				yield ('FAIL',None)
				continue

		print()

def parse_lastfm(inputf):

	with open(inputf,'r',newline='') as inputfd:
		reader = csv.reader(inputfd)

		for row in reader:
			try:
				artist,album,title,time = row
			except ValueError:
				err(f"{row} does not look like a valid entry. Scrobble not imported.")
				yield ('FAIL',None)
				continue

			try:
				yield ('SUCCESS',{
					'title': title,
					'artiststr': artist,
					'album': album,
					'timestamp': int(datetime.datetime.strptime(
						time + '+0000',
						"%d %b %Y %H:%M%z"
					).timestamp()),
					'duration':None
				})
			except Exception as e:
				err(f"{entry} could not be parsed. Scrobble not imported. ({repr(e)})")
				yield ('FAIL',None)
				continue
