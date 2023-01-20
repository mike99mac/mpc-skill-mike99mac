#
#            DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE
#   TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION
#
#  0. You just DO WHAT THE FUCK YOU WANT TO.
#
import csv
from dataclasses import dataclass
from enum import Enum
import logging
from .music_info import Music_info
from pathlib import Path
import random
import urllib.parse
from random import shuffle
import re
import subprocess
from typing import Union, Optional, List, Iterable

class MediaItemType(Enum):
  ARTIST = "MusicArtist"
  ALBUM = "MusicAlbum"
  SONG = "Audio"
  OTHER = "Other"

class MpcClient():
  """ Communicates with mpd using mpc calls """
  music_dir: Path
  music_dir: str                           # usually /media/ due to automount
  max_tracks: int                          # maximum number of tracks to queue
  mpc_rc: str                              # return code from last mpc call
  station_name: str                   
  station_genre: str  
  # station_country: str  
  # station_language: str 
  # station_ads: str    
  station_URL: str 
  request_type: str                        # "genre", "country", "language", "random" or "next_station"
  list_lines: list                         # all radio stations in the CSV file
  next_indices: list                       # indices matching current request type
  
  def __init__(self, music_dir: Path):
    self.log = logging.getLogger(__name__)
    self.music_dir = music_dir
    self.max_tracks = 50                   
    self.mpc_rc = "none"                       
    self.station_name = "unknown"                   
    self.station_genre = "unknown"
    # self.station_country = "unknown"
    # self.station_language = "unknown"
    # self.station_ads = "unknown" 
    self.station_URL = "unknown"  
    self.request_type = "unknown"  
    self.list_lines = []
    self.next_indices = []                 # no next station to start

  def initialize(self, music_dir: Path):  
    """ 
    Turn mpc "single" off so player keeps playing music   
    Return: boolean
    """
    try:
      result = subprocess.check_output("/usr/bin/mpc single off", shell=True) 
    except subprocess.CalledProcessError as e:      
      self.mpc_rc = str(e.returncode)
      self.log.log(20, "__init__():  mpc single off return code = "+str(e.returncode)) 

  def restart_mpd(self):
    """ 
    Restart the mpd service   
    Hopefully this will not be necessary, but the pulseaudio connection is sometimes not solid
    Return: True or False 
    """
    cmd = "sudo /usr/sbin/service mpd restart"
    self.log.log(20, "restart_mpd(): UH-OH - restarting mpd service - THIS SHOULD NOT BE NECESSARY!!!!")
    try:
      self.log.log(20, "restart_mpd(): running command: "+cmd)
      result = subprocess.check_output(cmd, shell=True) 
    except subprocess.CalledProcessError as e:      
      self.mpc_rc = str(e.returncode)
      self.log.log(20, "restart_mpd(): command "+cmd+" returned: "+self.mpc_rc)
      return False
    return True  

  def mpc_cmd(self, arg1, arg2 = None):
    """ 
    Run any mpc command that takes one or two arguments
    If the command fails, restart the mpd service and try again   
    Param: arg 1 - such as "clear" or "play"
           arg 2 - args to commands such as "add" or "load" 
    Return: True or False 
    """
    self.log.log(20, "mpc_cmd(): arg1 = "+arg1+" arg2 = "+str(arg2))
    cmd = "/usr/bin/mpc "+arg1
    if arg2 != None:     
      cmd = cmd+" "+arg2
    try:
      self.log.log(20, "mpc_cmd(): running command: "+cmd)
      result = subprocess.check_output(cmd, shell=True) 
      self.log.log(20, "mpc_cmd(): result: "+str(result))
    except subprocess.CalledProcessError as e:    
      self.mpc_rc = str(e.returncode)
      # restarting mpd is not working :((
      # self.log.log(20, "mpc_cmd(): command "+cmd+" returned: "+self.mpc_rc+" restarting mpd and trying again...")
      # if self.restart_mpd() != True:
      #    self.log.log(20, "mpc_cmd(): restart_mpd() failed")
      #    return False 
      # try:
      #   self.log.log(20, "mpc_cmd(): running command: "+cmd)
      #   result = subprocess.check_output(cmd, shell=True) 
      # except subprocess.CalledProcessError as e:      
      #   self.mpc_rc = str(e.returncode)
      #   self.log.log(20, "mpc_cmd(): command "+cmd+" failed again - returned: "+self.mpc_rc)
      #   return False
    self.log.log(20, "mpc_cmd(): returning True at bottom")    
    return True  

  def mpc_update(self, wait: bool = True):
    """ Update the mpd database by searching for music files """
    cmd = "/usr/bin/mpc update"
    if wait:
      cmd.append("--wait")
    self.log.info("mpc_update() running command: "+cmd)
    subprocess.check_call(cmd)

  def start_music(self, music_info: Music_info):
    """ 
    Start playing the music passed in the music_info object   
    Return: boolean
    """
    self.log.log(20, "CPS_start(): running: /usr/bin/mpc clear")
    subprocess.check_output("/usr/bin/mpc clear", shell=True) 
    i = 0
    for next_file in music_info.track_files: # add track(s) to the queue
      i += 1
      if self.mpc_cmd("add", next_file) != True:
        self.log.log(20, "start_music(): mpc_cmd(add, "+next_file+") failed")
        return False
    if i > 1:  
      self.log.log(20, "start_music(): added "+str(i)+" tracks to the playlist")

    if self.mpc_cmd("play") != True:
        self.log.log(20, "start_music(): mpc_cmd(play) failed")
        return False 

  def _search_music(self, command_type: str, query_type: Optional[str] = None, music_name: Optional[str] = None) -> List[List[str]]:
    """
    This handles two cases. One: a search for a particular song, artist, etc.
    Two: a 'listall' command to return all music.
    mpc syntax: https://www.musicpd.org/doc/mpc/html/#cmdoption-f
    """
    self.log.log(20, "_search_music(): command_type = "+command_type+" query_type = "+str(query_type)+" music_name = "+str(music_name))
    cmd = ["mpc", command_type, "--format", "%artist%\t%album%\t%title%\t%time%\t%file%"]
    if query_type and music_name != None:
      cmd.extend([query_type, music_name])
    self.log.log(20, "_search_music(): cmd = "+str(cmd))  
    return [
      line.split("\t")
      for line in subprocess.check_output(cmd, universal_newlines=True).splitlines()
      if line.strip()
    ]

  def _time_to_seconds(self, time_str: str) -> int:
    """ convert HR:MIN:SEC to number of seconds """
    parts = time_str.split(":", maxsplit=2)
    assert parts
    hours, minutes, seconds = 0, 0, 0

    if len(parts) == 3:
      hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
    elif len(parts) == 2:
      minutes, seconds = int(parts[0]), int(parts[1])
    else:
      seconds = int(parts[0])
    return (hours * 60 * 60) + (minutes * 60) + seconds
  
  def parse_common_phrase(self, phrase):
    """
    Perform "brute force" parsing of a music play request
    Music playing vocabulary:
      play (track|song|title|) {track} by (artist|band|) {artist}
      play (album|record) {album} by (artist|band) {artist}
      play (any|all|my|random|some|) music 
      play (playlist) {playlist}
      play (genre) {genre}     
    Returns: Music_info object

    """
    artist_name = "unknown_artist"
    found_by = "yes"                     # assume "by" is in the phrase
    intent = "unknown"                   # album, album-artist, artist, genre, music, playlist,
                                         #   track, track-artist, unknown_artist or unknown
    match_type = "unknown"               # album, artist, song or unknown
    music_name = ""                      # search term of music being sought
    track_files = []                      # files of songs to be played

    phrase = phrase.lower()
    self.log.log(20, "parse_common_phrase() phrase in lower case: " + phrase)

    # check for a partial request with no music_name
    match phrase:
      case "album" | "track" | "song" | "artist" | "genre" | "playlist":
        self.log.log(20, "parse_common_phrase() not enough information in request "+str(phrase))
        mesg_info = {"phrase": phrase}
        self.log.log(20, "parse_common_phrase() mesg_info = "+str(mesg_info))
        ret_val = Music_info("song", "not_enough_info", {"phrase": phrase}, None)
        self.log.log(20, "parse_common_phrase() ret_val.mesg_info = "+str(ret_val.mesg_info))
        return ret_val
    key = re.split(" by ", phrase)
    if len(key) == 1:                    # did not find "by"
      found_by = "no"
      music_name = str(key[0])           # check for all music, genre and playlist
      self.log.log(20, "parse_common_phrase() music_name = "+music_name)
      match music_name:
        case "any music" | "all music" | "my music" | "random music" | "some music" | "music":
          self.log.log(20, "parse_common_phrase() removed keyword "+music_name+" from music_name")
          ret_val = self.get_music("music", music_name, artist_name)
          return ret_val
      key = re.split("^genre ", music_name)
      if len(key) == 2:                  # found first word "genre"
        genre = str(key[1])
        self.log.log(20, "parse_common_phrase() removed keyword "+music_name+" from music_name")
        ret_val = self.get_music("genre", genre, artist_name)
        return ret_val 
      else:
        key = re.split("^playlist ", music_name)
        if len(key) == 2:                # found first word "playlist"
          playlist = str(key[1])
          self.log.log(20, "parse_common_phrase() removed keyword "+music_name+" from music_name")
          ret_val = self.get_music("playlist", playlist, artist_name)
          return ret_val
    elif len(key) == 2:                  # found one "by"
      music_name = str(key[0])
      artist_name = str(key[1])          # artist name follows "by"
      self.log.log(20, "parse_common_phrase() found the word by - music_name = "+music_name+" artist_name = "+artist_name)
    elif len(key) == 3:                  # found "by" twice - assume first one is in music
      music_name = str(key[0]) + " by " + str(key[1]) # paste the track or album back together
      self.log.log(20, "parse_common_phrase() found the word by twice: assuming first is music_name")
      artist_name = str(key[2])
    else:                                # found more than 2 "by"s - what to do?
      music_name = str(key[0])

    # look for leading keywords in music_name
    key = re.split("^album |^record ", music_name)
    if len(key) == 2:                    # found first word "album" or "record"
      match_type = "album"
      music_name = str(key[1])
      if found_by == "yes":
        intent = "album-artist"
      else:
        intent = "album"
      self.log.log(20, "parse_common_phrase() removed keyword album or record")
    else:                                # leading "album" not found
      key = re.split("^track |^song |^title ", music_name)
      if len(key) == 2:                  # leading "track", "song" or "title" found
        music_name = str(key[1])
        match_type = "song"
        if found_by == "yes":            # assume artist follows 'by'
          intent = "track-artist"
        else:                            # assume track
          intent = "track"
        self.log.log(20, "parse_common_phrase() removed keyword track, song or title")
      else:                              # leading keyword not found
        key = re.split("^artist |^band ", music_name) # remove "artist" or "band" if first word
        if len(key) == 2:                # leading "artist" or "band" found
          music_name = "all_music"       # play all the songs they have
          artist_name = str(key[1])
          match_type = "artist"
          intent = "artist"
          self.log.log(20, "parse_common_phrase() removed keyword artist or band from music_name")
        else:                            # no leading keywords found yet
          self.log.log(20, "parse_common_phrase() no keywords found: in last else clause")
          if found_by == "yes":
            intent = "unknown_artist"    # found artist but music could be track or album
    key = re.split("^artist |^band ", artist_name) # remove "artist" or "band" if first word
    if len(key) == 2:                    # leading "artist" or "band" found in artist name
      artist_name = str(key[1])
      self.log.log(20, "parse_common_phrase() removed keyword artist or band from artist_name")
    self.log.log(20, "parse_common_phrase() calling get_music with: "+intent+", "+music_name+", "+artist_name)
    ret_val = self.get_music(intent, music_name, artist_name) 
    return ret_val

  def get_album(self, album_name, album_id, artist_name):
    """
    return files for one album 
    """
    self.log.log(20, "get_album() album_name = "+album_name+" artist_name = "+artist_name)
    artist_found = "none"
    results = self._search_music("search", "album", album_name)    
    num_hits = len(results)
    self.log.log(20, "get_album() num_hits = " + str(num_hits))
    if num_hits == 0: 
      self.log.log(20, "get_album() _get() did not find an album matching "+str(album_name))
      mesg_info = {"album_name": album, "artist_name": artist}
      return Music_info(None, "music_not_found", mesg_info, [])
    track_files = []                      # at least one hit
    correct_artist = True
    for artist_found, album_found, title, time_str, relative_path in results:
      if album_found.lower() != album_name: # not an exact match
        self.log.log(20, "get_album() skipping album found that does not match: "+album_found.lower())
        continue 
      next_track='"'+self.music_dir+relative_path+'"'  
      self.log.log(20, "get_album() adding track: "+next_track+" to queue")     
      track_files.append(next_track) # add track to queue
      if artist_name != "unknown_artist" and artist_name != artist_found.lower(): # wrong artist  
        correct_artist = False  
    if correct_artist == False:    
      self.log.log(20, "get_album() playing album "+str(album_name)+" by "+str(artist_found)+" not by "+str(artist_name))
      mesg_file = "diff_album_artist"
      mesg_info = {"album_name": album_name, "artist_found": artist_found}
    else:   
      self.log.log(20, "get_album() found album "+str(album_name)+" by artist"+artist_found)    
      mesg_file = "playing_album"
      mesg_info = {"album_name": album_found, "artist_name": artist_found}
    return Music_info("album", mesg_file, mesg_info, track_files)

  def get_artist(self, artist_name):
    """
    return tracks for the requested artist  
    """
    self.log.log(20, "get_artist() called with artist_name "+str(artist_name))
    results = self._search_music("search", "artist", artist_name)    
    num_hits = len(results)
    self.log.log(20, "get_artist() num_hits = "+str(num_hits))
    
    random.shuffle(results)              # shuffle tracks
    track_files = []
    i = 0                                # counter
    for artist_found, album_found, title, time_str, relative_path in results:
      if artist_found.lower() != artist_name: # not an exact match
        self.log.log(20, "get_artist() skipping artist found that does not match: "+artist_found.lower())
        continue   
      next_track='"'+self.music_dir + relative_path+'"'  
      self.log.log(20, "get_artist() adding track: "+next_track+" to queue")     
      track_files.append(next_track)     # add track to queue
      i += 1                             # increment counter
      if i == self.max_tracks:           # that's enough 
        self.log.log(20, "get_artist() reached maximum number of tracks to queue: "+str(self.max_tracks))
        break
    mesg_info = {"artist_name": artist_name}    
    if i == 0:                           # no hits
      self.log.log(20, "get_artist() _get() did not find an artist matching "+str(artist_name))
      return Music_info(None, "artist_not_found", mesg_info, [])
    else:
      return Music_info("artist", "playing_artist", mesg_info, track_files)
 
  def get_music_info(self, match_type, mesg_file, mesg_info, results): 
    """
    Given the results of an mpc search. return a Music_info object 
    """
    self.log.log(20, "get_music_info() match_type = "+str(match_type)+" mesg_file = "+mesg_file+" mesg_info = "+str(mesg_info))
    track_files = []   
    for artist_found, album_found, title, time_str, relative_path in results:
      next_track='"'+self.music_dir+relative_path+'"'  # enclose file name in double quotes 
      self.log.log(20, "get_music_info() adding track: "+next_track+" to queue")     
      track_files.append(next_track)     # add track to queue  
    ret_val = Music_info(match_type, mesg_file, mesg_info, track_files) 
    return ret_val

  def get_all_music(self):
    """
    Return up to max_tracks random tracks from all music in the library
    """
    self.log.log(20, "get_all_music() getting random tracks")
    results = self._search_music("listall") 
    if len(results) == 0:   
      self.log.log(20, "get_all_music() did not find any music")
      mesg_info = {"music_name": "all music"}
      return Music_info(None, "music_not_found", mesg_info, [])
    random.shuffle(results)              # shuffle tracks
    results = results[0:self.max_tracks] # prune to max number of tracks
    num_hits = len(results)
    self.log.log(20, "get_all_music() num_hits = " + str(num_hits))
    mesg_info = {"num_hits": num_hits}
    ret_val = self.get_music_info("song", "playing_random", mesg_info, results)
    return ret_val
    
  def get_genre(self, genre_name):
    """
    Return up to max_tracks tracks for a requested genre 
    """
    self.log.log(20, "get_genre(): called with genre_name: "+genre_name)
    results = self._search_music("search", "genre", genre_name) 
    if len(results) == 0: 
      self.log.log(20, "get_genre() did not find a genre "+str(genre_name))
      return Music_info(None, "genre_not_found", {"genre_name": genre_name}, [])
    random.shuffle(results)              # shuffle tracks found
    results = results[0:self.max_tracks] # prune to max number of tracks
    mesg_info = {"genre_name": genre_name}
    ret_val = self.get_music_info("song", "playing_genre", mesg_info, results)
    return ret_val

  def get_playlist(self, playlist):
    """
    Search for playlist and if found, return all tracks
    """    
    self.log.log(20, "get_playlist() called with playlist: "+playlist)
    
    return Music_info("song", "", {}, track_files)
    
  def get_track(self, track_name, artist_name):
    """
    Get track by name, optionally by a specific artist
    If artist is not specified, it is passed in as "unknown_artist"
    """
    self.log.log(20, "get_track() called with track_name "+track_name+" artist_name "+artist_name)
    results = self._search_music("search", "title", track_name)    
    num_recs = len(results)
    if num_recs == 0:                    # no hits
      self.log.log(20, "get_track(): did not find a track matching"+track_name)
      if artist_name == "unknown_artist":
        mesg_file = "track_not_found"
        mesg_info = {"track_name": track_name}
      else:
        mesg_file = "track_artist_not_found"
        mesg_info = {"track_name": track_name, "artist_name": artist_name}   
      return Music_info(None, mesg_file, mesg_info, [])  
    
    # one or more hits
    exact_match = -1                     # no exact match yet
    index = 0
    track_files = []                     # return value(s)
    possible_files = []                  # possible return values
    possible_artists = []                # corresponding artists
    possible_albums = []                 # corresponding albums
    for artist_found, album_found, track_found, time_str, relative_path in results:
      if track_found.lower() == track_name: # track name matches
         possible_files.append('"'+self.music_dir + relative_path+'"')
         possible_artists.append(artist_found)
         possible_albums.append(album_found)
         if artist_name != "unknown_artist" and artist_found.lower() == artist_name: # exact match
           exact_match = index
           break
      index += 1
    if exact_match == -1:                # track and artist do not both match 
      if index > 0:                      # multiple hits
        num_hits = len(possible_files)
        index = random.randrange(num_hits) # choose a random track 
        self.log.log(20, "get_track() random track index = "+str(index)) 
    track_files.append(possible_files[index])
    mesg_file = "playing_track"
    mesg_info = {'track_name': track_name, 'artist_name': possible_artists[index], 'album_name': possible_albums[index]}
      
    # if artist was specified, verify it is correct
    if artist_name != "unknown_artist" and artist_name != artist_found: # wrong artist _ speak correct artist before playing 
      self.log.log(20, "get_track() found track "+str(track_name)+" by "+str(artist_found)+" not by "+str(artist_name))
      mesg_file = "diff_artist"
      mesg_info = {"track_name": track_name, "album_name": album_found, "artist_found": artist_found}
    return Music_info("song", mesg_file, mesg_info, track_files) 

  def get_unknown_music(self, music_name, artist_name):
    """
    Search on a music search term - could be album, artist or track
    """
    self.log.log(20, "get_unknown_music() music_name = "+music_name+" artist_name = "+artist_name)
    track_files = []                     # list of tracks to play
    for music_type in ["artist", "album", "title"]:
      results = self._search_music("search", music_type, music_name)    
      num_recs = len(results)
      if num_recs == 0:                  # no hit
        continue                         # iterate loop
      self.log.log(20, "get_unknown_music() found "+str(num_recs)+" hits with music_type = "+music_type)  
      match music_type:
        case "artist":                   
          for artist, album, title, time_str, relative_path in results:
            if artist.lower() == music_name: # exact match
              track_files.append('"'+self.music_dir + relative_path+'"')
          num_exact = len(track_files)
          if num_exact == 0:
            continue                     # iterate loop
          else:      
            mesg_info = {"artist_name": artist}
            ret_val = Music_info("artist", "playing_artist", mesg_info, track_files)
        case "album":                    # queue multiple tracks
          for artist, album, title, time_str, relative_path in results:
            track_files.append('"'+self.music_dir+relative_path+'"')
          mesg_info = {"album_name": album, "artist_name": artist}
          ret_val = Music_info("album", "playing_album", mesg_info, track_files)
        case "title":                    # queue one track
          index = random.randrange(num_recs) # choose a random track 
          self.log.log(20, "get_unknown_music() random track index = "+str(index))
          track_files.append('"'+self.music_dir + results[index][4]+'"') # relative path is fifth value 
          self.log.log(20, "get_unknown_music() track_files = "+str(track_files))
          mesg_info = {"track_name": results[index][2], "album_name": results[index][1], "artist_name": results[index][0]}
          ret_val = Music_info("song", "playing_track", mesg_info, track_files)
      return ret_val   

    # if we fall through, no music was found 
    self.log.log(20, "search_music(): did not find music matching "+music_name) 
    return Music_info(None, "music_not_found", {"music_name": music_name}, None )
    
  def get_music(self, intent, music_name, artist_name):
    """
    Search for track_files with one search terms and an optional artist name
    intent can be: album, album_artist, artist, music, track, track_artist, unknown_artist or unknown
    call one of:
      get_album()         play an album
      get_artist()        play an artist
      get_all_music()     play "full random" 
      get_genre()         play a music genre 
      get_playlist()      play a saved playlist
      get_track()         play a specific track
      get_unknown_music() play something that might be an album, an artist or a track 
    Return: Music_info object  
    """
    self.log.log(20, "get_music() intent = "+intent+" music_name = "+music_name+" artist_name = "+artist_name) 
    match intent:
      case "album":
        ret_val = self.get_album(music_name, -1, "unknown_artist") # no album id
      case "album_artist":
        ret_val = self.get_album(music_name, -1, artist_name) # no album id
      case "artist":
        ret_val = self.get_artist(artist_name) # no artist_id 
      case "genre":                   
        ret_val = self.get_genre(music_name) 
      case "music":                      # full random
        ret_val = self.get_all_music()
      case "playlist": 
        ret_val = self.get_playlist(music_name)  
      case "track":                      # call get_track with unknown track ID
        ret_val = self.get_track(music_name, "unknown_artist")
      case "track_artist":           
        ret_val = self.get_track(music_name, artist_name)
      case "unknown_artist":
        ret_val = self.get_unknown_music(music_name, artist_name)
      case "unknown":
        ret_val = self.get_unknown_music(music_name, "unknown_artist")
      case _:                            # unexpected
        self.log.log(20, "get_music() INTERNAL ERROR: intent is not supposed to be: "+str(intent))
        ret_val = Music_info(None, None, None, None)      
    return ret_val

  def manipulate_playlists(self, utterance):
    """
    List, create, add to, remove from and delete playlists
    Vocabulary for manipulating playlists:
      (create|make) playlist {playlist} from track {track}
      (delete|remove) playlist {playlist}
      add (track|song|title) {track} to playlist {playlist}
      add (album|record) {album} to playlist {playlist}
      (remove|delete) (track|song|title) {track} from playlist {playlist}
      (remove|delete) (album|record) {album} from playlist {playlist}
      list (my|) playlists
      what playlists (do i have|are there)
      what are (my|the) playlists
    return: file name of .dialog file (str) to speak and data to be added (dict)
    """
    self.log.log(20, "manipulate_playlists() called with utterance: "+utterance) 
    words = utterance.split()            # split request into words
    match words[0]:                      
      case "create" | "make":  
        phrase = words[2:]               # skip first word
        phrase = " ".join(phrase)        # convert to string
        self.log.log(20, "manipulate_playlists() phrase = "+phrase) 
        mesg_file, mesg_info = self.create_playlist(phrase) 
      case "remove" | "delete":      
        if words[1] == "playlist":
          phrase = words[2:]             # skip first word
          phrase = " ".join(phrase)      # convert to string
          mesg_file, mesg_info = self.delete_playlist(phrase) 
        else:                       
          mesg_file, mesg_info = self.delete_from_playlist(words[1:]) 
      case "add":
        music_type = "unknown"    
        match words[0]:                 
          case "track"|"song"|"title":
            music_type = "track"
          case "album"|"record":
            music_type = "album"
        phrase = words[1:]               # delete first word
        phrase = " ".join(phrase)        # convert to string
        mesg_file, mesg_info = self.add_to_playlist(music_type, phrase) 
      case "list"|"what":  
        mesg_file, mesg_info = self.list_playlists()
    self.log.log(20, "manipulate_playlists() returned: "+mesg_file+" and "+str(mesg_info))
    return mesg_file, mesg_info

  def get_playlist(self, playlist_name):
    """
    Load and play a playlist, if it exists
    Return: True or false
    """
    cmd = "/usr/bin/mpc load "+playlist_name
    self.log.log(20, "get_playlist(): calling: "+cmd)
    try:
      result = subprocess.check_output(cmd, shell=True)
    except subprocess.CalledProcessError as e: 
      self.mpc_rc = e.returncode
      self.log.log(20, "get_playlist(): did not find playlist: "+playlist_name)
      return False
    return True      

  def add_music_to_playlist(self, music_type, playlist_name, music_name):
    """
    Add a track or all the songs on an album to a playlist 
    :type music_type: str "track" or "album"
    :type x: numbers.Real
    :return: True or false
    """
    self.log.log(20, "add_music_to_playlist(): called with music_type: "+music_type+" playlist_name: "+playlist_name+" music_name: "+music_name)
    match music_type:
      case "track":  
        music_info = self.get_track(music_name, "unknown_artist") 
      case "album":  
        music_info = self.get_album(music_name, "unknown_artist")   
    if music_info.track_files == None:   # did not find track/album
      self.log.log(20, "add_music_to_playlist() did not find "+music_type+" "+music_name) 
      return False
    self.log.log(20, "add_music_to_playlist() music_info.track_files = "+str(music_info.track_files))
    # TODO: handle adding all tracks in an album here - just pick one track for now
    num_hits = len(music_info.track_files) 
    if num_hits > 1:                     # multiple hits
      self.log.log(20, "add_music_to_playlist() found "+str(num_hits)+" tracks - choosing one")
      index = random.randrange(num_hits) # choose a random track      
      file_name = music_info.track_files[index]
    else:  
      file_name = music_info.track_files[0]
    if self.mpc_cmd("add", file_name) != True:
       self.log.log(20, "mpc_cmd(add, "+file_name+") failed")
       return False

    # To save a playlist, it first must be deleted:(not intuitive)  
    # cmd = "/usr/bin/mpc rm "+playlist_name  # remove playlist  
    # self.log.log(20, "add_music_to_playlist(): calling: "+cmd)
    # try:
    #   result = subprocess.check_output(cmd, shell=True) 
    # except subprocess.CalledProcessError as e: 
    #   self.log.log(20, "add_music_to_playlist(): command failed")
    #   self.mpc_rc = e.returncode
    #   return False
    cmd = "/usr/bin/mpc save "+playlist_name  # save playlist  
    self.log.log(20, "add_music_to_playlist(): calling: "+cmd)
    try:
      result = subprocess.check_output(cmd, shell=True) 
    except subprocess.CalledProcessError as e: 
      self.log.log(20, "add_music_to_playlist(): command failed")
      self.mpc_rc = e.returncode
      return False 
    return True 
  
  def create_playlist(self, phrase): 
    """
    Create requires a playlist name and music name as Mpc playlists cannot be empty
    Vocabulary: (create|make) playlist {playlist} from (track|song|title) {track}
    Return:     mesg_file, mesg_info
    """
    self.log.log(20, "create_playlist() called with phrase: "+phrase)
    key = re.split("from track |from song |from title ", phrase)
    if len(key) == 1:                    # unexpected 
      self.log.log(20, "create_playlist() 'from track' not found in phrase")
      mesg_info = {"phrase": phrase} 
      return 'missing_from', mesg_info
    playlist_name = key[0].strip(' ').replace(' ', '_') # replace spaces with underscores
    music_name = key[1]
    self.log.log(20, "create_playlist() playlist_name = "+playlist_name+" music_name = "+music_name)
    rc = self.get_playlist(playlist_name)    # check if playlist already exists
    if rc == True:                      # it exists
      self.log.log(20, "create_playlist() playlist already exists: "+playlist_name)
      mesg_info = {"playlist_name": playlist_name}
      return "playlist_exists", mesg_info

    # add the track to the playlist  
    rc = self.add_music_to_playlist("track", playlist_name, music_name)
    if rc == False:
      mesg_info = {"return_code": self.mpc_rc}
      return "bad_mpc_rc", mesg_info
    else:  
      mesg_info = {"playlist_name": playlist_name}  
      return "created_playlist", mesg_info

  def delete_playlist(self, phrase):
    """
    Delete a playlist
    Vocabulary: (delete|remove) playlist {playlist}
    Return: mesg_file, mesg_info
    """
    self.log.log(20, "delete_playlist() called with phrase: "+str(phrase))
    phrase = phrase.rstrip(' ').replace(' ', '_') # replace spaces with underscores
    cmd = "/usr/bin/mpc load "+phrase
    self.log.log(20, "delete_playlist(): calling: "+cmd)
    try:
      result = subprocess.check_output(cmd, shell=True)
    except subprocess.CalledProcessError as e: 
      self.log.log(20, "delete_playlist():  result.returncode = "+str(result.returncode))  
      mesg_info = {"playlist_name": phrase}
      return "playlist_not_found", mesg_info
    cmd = "/usr/bin/mpc rm "+phrase      # delete the playlist
    self.log.log(20, "delete_playlist(): calling: "+cmd)
    try:
      result = subprocess.check_output(cmd, shell=True) 
    except subprocess.CalledProcessError as e:          
      mesg_info = {'': result.returncode}
      mesg_info = {'return_code': result.returncode}
      return "bad_mpc_rc", mesg_info  
      self.log.log(20, "delete_playlist():  command return code = "+str(e.returncode))
    mesg_info = {"playlist_name": phrase}  
    self.mpc_clear()                     # clear playlist in memory
    return "deleted_playlist", mesg_info

  def add_to_playlist(self, music_type, phrase):
    """
    Add a track or an album to an existing playlist
    Params:
      music_type: "track" or "album"
      phrase:     all text after "add"
    Vocabulary:
    TODO: allow "by artist {artist}" in both
      add (track|song|title) {track} to playlist {playlist}
      add (album|record) {album} to playlist {playlist}
    """
    self.log.log(20, "add_to_playlist() called with phrase: "+phrase)
    key = re.split(" to playlist| two playlist| 2 playlist ", phrase)
    if len(key) == 1:                    # did not find "to playlist"
      self.log.log(20, "add_to_playlist() ERROR 'to playlist' not found in phrase")
      return "to_playlist_missing", {} 
    music_name = key[0]
    playlist_name = key[1] 
    playlist_name = playlist_name.strip(' ').replace(' ', '_') # replace spaces with underscores
    self.log.log(20, "add_to_playlist() music_name = "+music_name+" playlist_name = "+playlist_name)

    # verify playlist exists
    rc = self.get_playlist(playlist_name) 
    if rc == False:                      # not found
      self.log.log(20, "add_to_playlist() did not find playlist_name "+playlist_name)
      mesg_info = {'playlist_name': playlist_name}
      return "playlist_not_found", mesg_info
    
    # verify track or album exists  
    music_info = self.parse_common_phrase(music_name) 
    if music_info.track_files == None:
      self.log.log(20, "add_to_playlist() did not find track or album "+music_name)
      mesg_info = {"playlist_name": playlist_name} 
      return "playlist_missing_track", mesg_info

    self.log.log(20, "add_to_playlist() music_info.track_files = "+str(music_info.track_files))
    
    # add track to playlist  
    rc = self.add_music_to_playlist(music_type, playlist_name, music_name)
    if rc == False:
      mesg_info = {"return_code": self.mpc_rc}
      return "bad_mpc_rc", mesg_info
    else:  
      mesg_info = {"playlist_name": playlist_name}  
      return "created_playlist", mesg_info
    mesg_info = {'music_name': music_name, 'playlist_name': playlist_name}
    return "ok_its_done", mesg_info
    
  def delete_from_playlist(self, phrase):
    """
    Delete a track from a playlist
    Vocabulary:
      (remove|delete) (track|song|title) {track} from playlist {playlist}
      (remove|delete) (album|record) {album} from playlist {playlist}
    Return: mesg_file (str), mesg_info (dict)  
    """
    self.log.log(20, "delete_from_playlist() called with phrase: "+str(phrase))
    phrase = " ".join(phrase)            # convert list back to string
    key = re.split(" from playlist ", phrase)
    if len(key) == 1:                    # did not find "from playlist"
      self.log.log(20, "delete_from_playlist() ERROR 'from playlist' not found in phrase")
      return "to_playlist_missing", {} 
    music_name = key[0]
    playlist_name = key[1] 
    self.log.log(20, "delete_from_playlist() music_name = "+music_name+" playlist_name = "+playlist_name)

    # verify playlist exists
    rc = self.get_playlist(playlist_name) 
    if rc == False:                      # not found
      self.log.log(20, "delete_from_playlist() did not find playlist_name "+playlist_name)
      mesg_info = {'playlist_name': playlist_name}
      return "missing_playlist", mesg_info
    
    # verify track or album exists  
    music_info = self.parse_common_phrase(music_name) 
    if music_info.track_files == None:
      self.log.log(20, "delete_from_playlist() did not find track or album "+music_name)
      mesg_info = {"playlist_name": playlist_name, "music_name": music_name} 
      return "playlist_missing_track", mesg_info
    self.log.log(20, "delete_from_playlist() music_info.track_files = "+str(music_info.track_files))
    track_id = self.get_id_from_uri(music_info.track_files)
    self.log.log(20, "delete_from_playlist() track_id = "+track_id)
    # TODO: finish code
    return "ok_its_done", {}

  def list_playlists(self):
    """
    List all saved playlists
    Return: mesg_file (str), mesg_info (dict)  
    """
    self.log.log(20, "top of list_playlists()")
    cmd = ["/usr/bin/mpc ", "lsplaylists"]
    self.log.log(20, "list_playlists(): running command: "+str(cmd))
    playlists = {}
    rc = 0
    try:
      process = subprocess.check_output("/usr/bin/mpc lsplaylists", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      output, err = process.communicate() 
      rc = process.returncode 
      playlists = str(output)
      self.log.log(20, "list_playlists(): playlists = "+playlists+" rc = "+str(rc))
    except:
      self.log.log(20, "list_playlists(): return code: "+str(rc))
    if len(playlists) == 0:
      mesg_info={}
      return "playlists_not_found", mesg_info
    else:  
      mesg_info = {"playlists": playlists}  
      return "list_playlists", mesg_info 

  def get_next_station(self):
    """
    get next radio stations by genre, country, or language
    Return: index of station    
    """
    self.log.log(20, "get_next_station() self.request_type = "+self.request_type)     
    num_matches = len(self.next_indices)
    if num_matches == 0:                   # no previous request of genre, country or language 
      self.request_type = "random" 
      index = random.randrange(num_lines)  # choose a random station
    if num_matches == 1:                   # there is no next station
      self.log.log(20, "get_station() only one station matches request - forcing to random")
      self.request_type = "random" 
      index = random.randrange(num_lines)  # choose a random station
    else:      
      match_index = random.randrange(num_matches)  # index for list of stations matching request
      index = self.next_indices[match_index]       # index for list of all stations
    return index

  def get_matching_station(self, field_index, search_name):
    """
    Search for radio stations by genre, country, or language
    param: field_index: field number to search on 
           search_name: station, genre, language or country to search for
    Return: index of station or -1 when not found   
    """
    self.log.log(20, "get_matching_station() field_index: "+str(field_index)+" search_name = "+search_name)
    self.next_indices = []             # reset list of station indexes that match
    num_hits = 0
    index = 0
    for next_line in self.list_lines:
      # self.log.log(20, "get_station() next_line[1] = "+str(next_line[1].strip()))
      if search_name in next_line[field_index].strip():
        self.next_indices.append(index)     # save index of match
        num_hits += 1
      index += 1  
    if num_hits == 0:                      # music not found
      self.log.log(20, "get_matching_station() did not find "+self.request_type+" "+search_name+" in field number "+str(field_index)) 
      return -1                 
    self.log.log(20, "get_matching_station() self.next_indices = "+str(self.next_indices))
    matching_index = random.randrange(num_hits) # choose a random station if multiple hits
    return self.next_indices[matching_index] # index of a random matching station

  def get_station(self, search_name):
    """
    Play a radio station by genre, country, language, station name, or a random one
    param: search_name: item to search for 
    Return: music_info object  
    """
    self.log.log(20, "get_station() self.request_type: "+self.request_type+" search_name = "+search_name)
    input_file = open("/opt/mycroft/skills/mpc-skill-mike99mac/radio.stations.csv", "r+")
    reader_file = csv.reader(input_file)
    self.list_lines = list(reader_file)    # convert to list
    num_lines = len(self.list_lines)            # number of saved radio stations
    self.log.log(20, "get_station() num_lines = "+str(num_lines))
    mesg_info = {}
    track_files = []
    index = -1
    if search_name == "next_station":
      index = self.get_next_station()
    else:  
      match self.request_type:
        case "random":
          index = random.randrange(num_lines) # choose a random station 
          mesg_file = "playing_radio"  
          mesg_info = {"station_name": self.station_name, "station_genre": self.station_genre.replace("|", " or " )}
        case "genre":
          self.log.log(20, "get_station() searching for station by genre "+search_name) 
          index = self.get_matching_station(1, search_name)
          if index == -1:                    # station not found
            self.log.log(20, "get_station() did not find genre "+search_name) 
            mesg_info = {"request_type": self.request_type, "search_name": search_name}
            return Music_info("song", "radio_not_found", mesg_info, track_files)
        case "country":
          self.log.log(20, "get_station() searching for station from country "+search_name) 
          index = self.get_matching_station(2, search_name)
          if index == -1:                    # country not found
            self.log.log(20, "get_station() did not find country "+search_name) 
            mesg_info = {"country": search_name}
            return Music_info("song", "country_not_found", mesg_info, track_files)
        case "language":
          self.log.log(20, "get_station() searching for station in language "+search_name) 
          index = self.get_matching_station(3, search_name)
          if index == -1:                    # language not found
            self.log.log(20, "get_station() did not find language "+search_name) 
            mesg_info = {"language": search_name}
            return Music_info("song", "language_not_found", mesg_info, track_files)  
        case "station":
          self.log.log(20, "get_station() searching for station named "+search_name) 
          index = self.get_matching_station(0, search_name)
          if index == -1:                    # station not found
            self.log.log(20, "get_station() did not find language "+search_name) 
            mesg_info = {"language": search_name}
            return Music_info("song", "country_not_found", mesg_info, track_files)

    # clear the playlist
    if self.mpc_cmd("clear") != True:      # mpc failed
      self.log.log(20, "get_station() self.mpc_cmd(clear) failed")
      mesg_info = {"return_code": self.mpc_rc}
      return "bad_mpc_rc", mesg_info   

    # add the radio station to the playlist
    # self.index = index
    self.log.log(20, "get_station() index = "+str(index))
    self.station_name = self.list_lines[index][0].strip()
    self.station_genre = self.list_lines[index][1].strip()
    # self.station_country = list_lines[index][2].strip()
    # self.station_language = list_lines[index][3].strip()
    # self.station_ads = list_lines[index][4].strip()
    self.station_URL =  self.list_lines[index][5].strip()
    self.log.log(20, "get_station() adding station "+self.station_URL)
    if self.mpc_cmd("add", self.station_URL) != True: # mpc failed
      self.log.log(20, "get_station() self.mpc_cmd(add, "+self.station_URL+"} failed")
      mesg_info = {"return_code": self.mpc_rc}
      return "bad_mpc_rc", mesg_info    
    mesg_info = {"station_name": self.station_name, "station_genre": self.station_genre.replace("|", " or ")}  
    track_files = []
    track_files.append(self.station_URL)
    return Music_info("song", "playing_radio", mesg_info, track_files)

  def parse_radio(self, utterance):
    """
    Parse the request to play a radio station
    param: utterance from user
    Vocabulary:
      play (the|) radio
      play music (on the|on my|) radio
      play genre {genre} (on the|on my|) radio
      play station {station} (on the|on my|) radio
      play (the|) (radio|) station {station}
      play (the|) radio (from|from country|from the country) {country}
      play (the|) radio (spoken|) (in|in language|in the language) {language}
      play (another|a different|next) (radio|) station
      (different|next) (radio|) station
    Return: mesg_file (str), mesg_info (dict)  
    """
    self.log.log(20, "parse_radio() utterance: "+utterance)  
    utterance = utterance.replace('on the ', '') # remove unnecessary words
    utterance = utterance.replace('on my ', '')
    utterance = utterance.replace('the ', '')
    utterance = utterance.replace(' a ', ' ')
    self.log.log(20, "parse_radio() cleaned up utterance: "+utterance)  
    words = utterance.split()            # split request into words
    num_words = len(words)
    intent = "None"
    search_name = "None" 
    match words[0]:                      
      case "different" | "next":  
        self.log.log(20, "parse_radio() find next station - this.request_type = "+self.request_type)
        if self.request_type in "genre|country|language": # get next station of this type
          search_name = "next_station"
        else:  
          self.request_type = "random"
      case "play":      
        match words[1]:
          case "radio":
            if words[2] == "station":
              if num_words == 3:
                self.request_type = "random"
              elif words[3] == "from":
                self.request_type = "country"
                search_name = words[4]   
              else:
                self.request_type = "station"
                search_name = words[3]
            elif words[2] == "from":
              self.request_type = "country"
              search_name = words[3]   
            elif words[2] == "spoken" or words[2] == "in":
              self.request_type = "language"
              search_name = words[3]     
            else: 
              self.request_type = "random" 
          case "music"|"any":
            self.request_type = "random"
          case "genre":
            self.request_type = "genre"
            search_name = words[2]
          case "station":
            self.request_type = "station" 
            search_name = words[2]       
          case other:
            if words[2] == "radio" or words[2] == "station": 
               self.request_type = "genre"
               search_name = words[1]
            else:
              self.request_type = "random"
    mesg_info = {}        
    music_info = self.get_station(search_name) 
    return music_info
     