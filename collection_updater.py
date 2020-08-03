import re
import os
import requests
import configparser
import xml.etree.ElementTree as ET
from plexapi.server import PlexServer
from progress.bar import Bar

############################################################################################################################################
# Read values from settings.ini
############################################################################################################################################

ini_name = 'settings.ini'

if(not os.path.isfile(ini_name)):
    print('Could not find settings.ini')

ini = configparser.ConfigParser()
ini.read(ini_name)
config = ini['CONFIG']

enable_debug = config['enable_debug']

if enable_debug == 'True':
    enable_debug = True
else:
    enable_debug = False

# Plex server settings
PLEX_SERVER = config['plex_url']
PLEX_TOKEN = config['plex_token']

# Metadata settings
PREF_LOCAL_ART = config['prefer_local_art']

if PREF_LOCAL_ART == 'True':
    PREF_LOCAL_ART = True
else:
    PREF_LOCAL_ART = False

POSTER_ITEM_LIMIT = int(config['poster_item_limit'])
BACKGROUND_ITEM_LIMIT = int(config['background_item_limit'])

# TMDB settings
TMDB_APIKEY = config['api_key']

############################################################################################################################################
# Global variables
############################################################################################################################################

payload = {}
err_list = []

HEADERS = {'X-Plex-Token' : PLEX_TOKEN }

TMDB_URL = 'https://api.themoviedb.org/3'
TMDB_CONFIG = '%s/configuration?api_key=%s' % (TMDB_URL, TMDB_APIKEY)
TMDB_MOVIE = '%s/movie/%%s?api_key=%s&language=%%s' % (TMDB_URL, TMDB_APIKEY)
TMDB_COLLECTION = '%s/collection/%%s?api_key=%s&language=%%s' % (TMDB_URL, TMDB_APIKEY)
TMDB_COLLECTION_IMG = '%s/collection/%%s/images?api_key=%s' % (TMDB_URL, TMDB_APIKEY)

PLEX_SUMMARY = '%s/library/sections/%%s/all?type=18&id=%%s&summary.value=%%s' % PLEX_SERVER
PLEX_IMAGES = '%s/library/metadata/%%s/%%s?url=%%s' % PLEX_SERVER
PLEX_COLLECTIONS = '%s/library/sections/%%s/all?type=18' % PLEX_SERVER
PLEX_COLLECTIONS_ITEMS = '%s/library/metadata/%%s/children' % PLEX_SERVER

############################################################################################################################################
# main function
############################################################################################################################################

def main():
    section_dict = {}

    tmdb_conf_dict = GetTMDBData(TMDB_CONFIG)

    print(''.ljust(80, '='))
    print('Metadata retriever for TMDB collections')
    print(''.ljust(80, '='))

    plex = PlexServer(PLEX_SERVER, PLEX_TOKEN)
    plex_sections = plex.library.sections()

    print('\r\nYour movie libraries are:')
    print(''.ljust(80, '='))

    for plex_section in plex_sections:
        if plex_section.type != 'movie':
            continue

        print('ID: %s Name: %s' % (str(plex_section.key).ljust(4, ' '), plex_section.title))
        section_dict[plex_section.key] =  plex_section.title

    print(''.ljust(80, '='))

    if len(section_dict) == 0:
        print('Could not find any movie libraries.')
        return

    input_sections = input('\r\nEnter a whitespace separated list of library IDs to work on (e.g: 3 5 8 13):\r\n')
 
    # remove invalid characters from user input
    input_sections = ''.join(i for i in input_sections if i.isdigit() or i.isspace()).split()
    
    for section_id in input_sections:
        
        # ensure that it is a valid library
        if section_id not in section_dict:
           print('%s is not a valid library id.' % section_id)
           continue

        # Get all collections of library      
        plex_all_col_xml = GetPlexData(PLEX_COLLECTIONS % section_id)

        print(''.ljust(80, '='))
        print('Library: %s (%s collections)' % (section_dict[section_id], len(plex_all_col_xml)))
        print(''.ljust(80, '='))

        i = 0

        for plex_col_xml in plex_all_col_xml:
            plex_col_dict = plex_col_xml.attrib
            i += 1

            print('\r\n> %s [%s/%s]' % (plex_col_dict['title'], i, len(plex_all_col_xml)) )

            # only get data for collections that have no summary yet
            if plex_col_dict['summary'] != '':
                print('  Skipping collection because summary already exists.')
                continue

            plex_col_id = plex_col_dict['ratingKey']

            plex_col_mov_xml = GetPlexData(PLEX_COLLECTIONS_ITEMS % plex_col_id)
            tmdb_col_id, lang = GetTMDBCollectionID(plex, plex_col_mov_xml)

            if tmdb_col_id == -1:
                print('  Could not find a matching TMDB collection.')

                err_list.append('\r\n> %s' % plex_col_dict['title'])
                err_list.append('  Could not find a matching TMDB collection.')
                continue
                
            # get collection information
            tmdb_col_dict = GetTMDBData(TMDB_COLLECTION % (tmdb_col_id, lang)) 

            plex_col_title = plex_col_dict['title']

            if lang == 'en':
                plex_col_title = plex_col_dict['title'] + ' Collection'

            if tmdb_col_dict['name'] != plex_col_title and tmdb_col_dict['name'] + ' Collection' != plex_col_title:
                print('  Invalid collection, does not match with the TMDB collection: %s' % tmdb_col_dict['name'])

                err_list.append('\r\n> %s' % plex_col_title)
                err_list.append('  Invalid collection, does not match with the TMDB collection: %s' % tmdb_col_dict['name'])
                continue

            # get collection images
            tmdb_col_img_dict = GetTMDBData(TMDB_COLLECTION_IMG % (tmdb_col_id))

            print('  Found a total of %s posters and %s backgrounds.' % (len(tmdb_col_img_dict['posters']), len(tmdb_col_img_dict['backdrops']) ))

            poster_url_list = GetImages(tmdb_col_img_dict, tmdb_conf_dict, 'posters', lang, POSTER_ITEM_LIMIT)
            background_url_list = GetImages(tmdb_col_img_dict, tmdb_conf_dict, 'backdrops', lang, BACKGROUND_ITEM_LIMIT)

            # update data in plex now

            # 1 change summary
            print('  Updating summary.')
            r = requests.put(PLEX_SUMMARY % (section_id, plex_col_id, tmdb_col_dict['overview']), data=payload, headers=HEADERS)

            # 2 upload posters
            UploadImagesToPlex(poster_url_list, plex_col_id, 'poster', 'posters')

            # 3 upload backdrops
            UploadImagesToPlex(background_url_list, plex_col_id, 'art', 'backgrounds')

        # print failed libraries again
        if len(err_list) > 0:
            print('\r\nThe following libraries could not be updated:')
            print(''.ljust(80, '='))
            for line in err_list:
                print(line)

        err_list.clear()

    print('\r\nFinished updating libraries.')

############################################################################################################################################

def GetPlexData(url):
    r = requests.get(url, headers=HEADERS)
    col_movies = ET.fromstring(r.text)
    return col_movies

############################################################################################################################################

def GetPlexPosterUrl(plex_url):
    r = requests.get(plex_url, headers=HEADERS)
    root = ET.fromstring(r.text)

    for child in root:
        dict = child.attrib
        
        if dict['selected'] == '1':
            url = dict['key']
            return url[url.index('?url=') + 5:]

############################################################################################################################################

def UploadImagesToPlex(url_list, plex_col_id, image_type, image_type_name):
    if url_list:
        plex_main_image = ''

        bar = Bar('  Uploading %s:' % image_type_name, max=len(url_list))

        for background_url in url_list:
            #print( '  Uploading: %s' % background_url)
            bar.next()
            r = requests.post(PLEX_IMAGES % (plex_col_id, image_type + 's', background_url), data=payload, headers=HEADERS)
    
            if plex_main_image == '':
                plex_main_image = GetPlexPosterUrl(PLEX_IMAGES % (plex_col_id, image_type + 's', background_url))

        bar.finish()

        # set the highest rated image as selected again
        r = requests.put(PLEX_IMAGES % (plex_col_id, image_type, plex_main_image), data=payload, headers=HEADERS)

############################################################################################################################################

def GetTMDBCollectionID(plex, mov_in_col_xml):
    for mov_in_col in mov_in_col_xml:
        movie = plex.fetchItem(int(mov_in_col.attrib['ratingKey']))

        if enable_debug:
            print('Movie guid: %s' % movie.guid)

        if movie.guid.startswith('com.plexapp.agents.imdb://'): # Plex Movie agent
            match = re.search("tt[0-9]\w+", movie.guid)
        elif movie.guid.startswith('com.plexapp.agents.themoviedb://'): # TheMovieDB agent
            match = re.search("[0-9]\w+", movie.guid)

        if not match:
            continue

        movie_id = match.group()

        match = re.search("lang=[a-z]{2}", movie.guid)

        if match:
            lang = match.group()[5:]

        movie_dict = GetTMDBData(TMDB_MOVIE % (movie_id, lang))

        if movie_dict and 'belongs_to_collection' in movie_dict and movie_dict['belongs_to_collection'] != None:
            col_id = movie_dict['belongs_to_collection']['id']
            print('  Retrieved collection id: %s (from: %s id: %s language: %s)' % (col_id, movie.title, movie_id, lang))
            return col_id, lang

    return -1, ''

############################################################################################################################################

def GetTMDBData(url):
    try:      
        r = requests.get(url)

        if enable_debug:
            print('Requests in time limit remaining: %s' % r.headers['X-RateLimit-Remaining'])

        return r.json()
    except:
        print('Error fetching JSON from The Movie Database: %s' % url)

###########################################################################################################################################

def GetImages(img_dict, conf_dict, type, lang, artwork_item_limit):
    result = []

    if img_dict[type]:
        i = 0
        while i < len(img_dict[type]):
            poster = img_dict[type][i]

            # remove foreign posters
            if poster['iso_639_1'] is not None and poster['iso_639_1'] != 'en' and  poster['iso_639_1'] != lang:
               del img_dict[type][i]
               continue

            # boost the score for localized posters (according to the preference)
            if PREF_LOCAL_ART and poster['iso_639_1'] == lang:
                img_dict[type][i]['vote_average'] = poster['vote_average'] + 1
                #poster['vote_average'] = poster['vote_average'] + 1

            i += 1

        for i, poster in enumerate(sorted(img_dict[type], key=lambda k: k['vote_average'], reverse=True)):
            if i >= artwork_item_limit:
                break
            else:
                result.append(conf_dict['images']['base_url'] + 'original' + poster['file_path'])

    return result

############################################################################################################################################

main()