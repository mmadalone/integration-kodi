"""
Kodi Setup fields.

:copyright: (c) 2026 by Albaintor
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

from const import KODI_POWEROFF_COMMANDS, KodiObjectType

KODI_ARTWORK_LABELS = [
    {"id": "thumb", "label": {"en": "Thumbnail", "fr": "Standard"}},
    {"id": "fanart", "label": {"en": "Fan art", "fr": "Fan art"}},
    {"id": "poster", "label": {"en": "Poster", "fr": "Poster"}},
    {"id": "landscape", "label": {"en": "Landscape", "fr": "Paysage"}},
    {"id": "keyart", "label": {"en": "Key art", "fr": "Key art"}},
    {"id": "banner", "label": {"en": "Banner", "fr": "Affiche"}},
    {"id": "clearart", "label": {"en": "Clear art", "fr": "Clear art"}},
    {"id": "clearlogo", "label": {"en": "Clear logo", "fr": "Clear logo"}},
    {"id": "discart", "label": {"en": "Disc art", "fr": "Disc art"}},
    {"id": "icon", "label": {"en": "Icon", "fr": "Icône"}},
    {"id": "set.fanart", "label": {"en": "Fanart set", "fr": "Jeu de fanart"}},
    {"id": "set.poster", "label": {"en": "Poster set", "fr": "Jeu de poster"}},
]

KODI_ARTWORK_TVSHOWS_LABELS = [
    {"id": "thumb", "label": {"en": "Thumbnail", "fr": "Standard"}},
    {"id": "season.banner", "label": {"en": "Season banner", "fr": "Affiche de la saison"}},
    {"id": "season.landscape", "label": {"en": "Season landscape", "fr": "Saison en paysage"}},
    {"id": "season.poster", "label": {"en": "Season poster", "fr": "Affiche de la saison"}},
    {"id": "tvshow.banner", "label": {"en": "TV show banner", "fr": "Affiche de la série"}},
    {"id": "tvshow.characterart", "label": {"en": "TV show character art", "fr": "Personnages de la série"}},
    {"id": "tvshow.clearart", "label": {"en": "TV show clear art", "fr": "Affiche sans fond de la série"}},
    {"id": "tvshow.clearlogo", "label": {"en": "TV show clear logo", "fr": "Logo sans fond de la série"}},
    {"id": "tvshow.fanart", "label": {"en": "TV show fan art", "fr": "Fan art de la série"}},
    {"id": "tvshow.landscape", "label": {"en": "TV show landscape", "fr": "Affiche en paysage"}},
    {"id": "tvshow.poster", "label": {"en": "TV show poster", "fr": "Affiche de la série"}},
    {"id": "icon", "label": {"en": "Icon", "fr": "Icône"}},
]

# Patch 44: PVR / channel artwork preference. Default "icon" reads `art["icon"]`,
# which holds the channel logo consistently across real PVR (`image://pvrchannel_tv@...`
# from Kodi's PVR client) and PseudoTV (`image://special://...pseudotv.../logos/<channel>.png/`).
# The "thumbnail" sentinel is offered as an opt-in for users whose integration puts the
# channel logo at top-level `item['thumbnail']` instead — wraps bare `special://...` paths
# into `image://...` so the existing fetch pipeline can resolve them.
KODI_ARTWORK_CHANNELS_LABELS = [
    {"id": "icon", "label": {"en": "Channel logo (default)", "fr": "Logo de la chaîne (défaut)"}},
    {
        "id": "thumbnail",
        "label": {
            "en": "Top-level thumbnail (PseudoTV addon path / EPG image)",
            "fr": "Vignette principale (PseudoTV / image EPG)",
        },
    },
    {"id": "thumb", "label": {"en": "Currently-airing show poster", "fr": "Affiche du programme en cours"}},
    {"id": "poster", "label": {"en": "Poster", "fr": "Poster"}},
    {"id": "fanart", "label": {"en": "Fan art", "fr": "Fan art"}},
    {"id": "clearlogo", "label": {"en": "Clear logo", "fr": "Clear logo"}},
    {"id": "clearart", "label": {"en": "Clear art", "fr": "Clear art"}},
    {"id": "banner", "label": {"en": "Banner", "fr": "Affiche"}},
    {"id": "landscape", "label": {"en": "Landscape", "fr": "Paysage"}},
]

KODI_DEFAULT_ARTWORK = "thumb"
KODI_DEFAULT_TVSHOW_ARTWORK = "tvshow.poster"
KODI_DEFAULT_CHANNELS_ARTWORK = "icon"

KODI_BROWSING_SORT = {
    KodiObjectType.MOVIE: [
        {"id": "title", "label": {"en": "Name", "fr": "Nom"}},
        {"id": "dateadded descending", "label": {"en": "Date added", "fr": "Date de l'ajout"}},
        {"id": "rating descending", "label": {"en": "Rating", "fr": "Notation"}},
        {"id": "year", "label": {"en": "Year", "fr": "Année"}},
    ],
    KodiObjectType.FILE: [
        {"id": "", "label": {"en": "Name", "fr": "Nom"}},
        {"id": "date descending", "label": {"en": "Date", "fr": "Date"}},
        {"id": "file", "label": {"en": "File", "fr": "Fichier"}},
    ],
    KodiObjectType.ALBUM: [
        {"id": "album", "label": {"en": "Album", "fr": "Album"}},
        {"id": "artist", "label": {"en": "Artist", "fr": "Artiste"}},
        {"id": "dateadded descending", "label": {"en": "Date added", "fr": "Date de l'ajout"}},
        {"id": "rating descending", "label": {"en": "Rating", "fr": "Notation"}},
        {"id": "year", "label": {"en": "Year", "fr": "Année"}},
    ],
}

KODI_BROWSING_CATEGORIES = [
    {"id": "", "label": {"en": "Default", "fr": "Par défaut"}},
    {"id": "kodi://videos", "label": {"en": "Videos", "fr": "Vidéos"}},
    {"id": "kodi://videos/all", "label": {"en": "All videos", "fr": "Toutes les vidéos"}},
    {"id": "kodi://videos/current", "label": {"en": "Current videos", "fr": "Vidéos en cours"}},
    {"id": "kodi://videos/recent", "label": {"en": "Recently added videos", "fr": "Vidéos récemment ajoutées"}},
    {"id": "kodi://tvshows", "label": {"en": "TV Shows", "fr": "Séries"}},
    {"id": "kodi://tvshows/all", "label": {"en": "All TV Shows", "fr": "Toutes les séries"}},
    {"id": "kodi://tvshows/current", "label": {"en": "Current TV Shows", "fr": "Séries en cours"}},
    {
        "id": "kodi://tvshows/recent",
        "label": {"en": "Recently added TV Shows episodes", "fr": "Episodes de séries ajoutés récemment"},
    },
    {"id": "kodi://music", "label": {"en": "Music", "fr": "Musique"}},
    {"id": "kodi://music/albums", "label": {"en": "Music albums", "fr": "Albums de musique"}},
    {"id": "kodi://music/playlists", "label": {"en": "Music playlists", "fr": "Listes de musique"}},
    {"id": "kodi://sources", "label": {"en": "Sources", "fr": "Sources"}},
    {"id": "kodi://sources/videos", "label": {"en": "Video sources", "fr": "Sources de vidéos"}},
    {"id": "kodi://sources/music", "label": {"en": "Music sources", "fr": "Sources de musique"}},
    {"id": "kodi://sources/pictures", "label": {"en": "Pictures sources", "fr": "Sources d'images"}},
    {"id": "kodi://pvr", "label": {"en": "Live TV", "fr": "TV en direct", "de": "Live-TV"}},
    {"id": "kodi://pvr/tv", "label": {"en": "TV channels", "fr": "Chaînes TV", "de": "TV-Sender"}},
    {"id": "kodi://pvr/radio", "label": {"en": "Radio channels", "fr": "Chaînes radio", "de": "Radiosender"}},
    {"id": "kodi://addons", "label": {"en": "Addons", "fr": "Extensions", "de": "Addons"}},
    {"id": "kodi://addons/video", "label": {"en": "Video addons", "fr": "Extensions vidéo", "de": "Video-Addons"}},
    {"id": "kodi://addons/audio", "label": {"en": "Music addons", "fr": "Extensions musique", "de": "Musik-Addons"}},
    {"id": "kodi://favorites", "label": {"en": "Favorites", "fr": "Favoris", "de": "Favoriten"}},
]

SETUP_FIELDS = [
    {
        "field": {"text": {"value": ""}},
        "id": "username",
        "label": {"en": "Username", "fr": "Utilisateur"},
    },
    {
        "field": {"text": {"value": ""}},
        "id": "password",
        "label": {"en": "Password", "fr": "Mot de passe"},
    },
    {
        "field": {"text": {"value": "9090"}},
        "id": "ws_port",
        "label": {"en": "Websocket port", "fr": "Port websocket"},
    },
    {
        "field": {"text": {"value": "8080"}},
        "id": "port",
        "label": {"en": "HTTP port", "fr": "Port HTTP"},
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "ssl",
        "label": {"en": "Use SSL", "fr": "Utiliser SSL"},
    },
    {
        "field": {"dropdown": {"value": KODI_DEFAULT_ARTWORK, "items": KODI_ARTWORK_LABELS}},
        "id": "artwork_type",
        "label": {
            "en": "Artwork type to display",
            "fr": "Type d'image média à afficher",
        },
    },
    {
        "field": {"dropdown": {"value": KODI_DEFAULT_TVSHOW_ARTWORK, "items": KODI_ARTWORK_TVSHOWS_LABELS}},
        "id": "artwork_type_tvshows",
        "label": {
            "en": "Artwork type to display for TV Shows",
            "fr": "Type d'image média à afficher pour les séries",
        },
    },
    {
        "field": {"dropdown": {"value": KODI_DEFAULT_CHANNELS_ARTWORK, "items": KODI_ARTWORK_CHANNELS_LABELS}},
        "id": "artwork_type_channels",
        "label": {
            "en": "Artwork type to display for PVR/Channels",
            "fr": "Type d'image média à afficher pour les chaînes PVR",
        },
    },
    {
        "field": {
            "dropdown": {
                "value": "",
                "items": KODI_BROWSING_CATEGORIES,
            }
        },
        "id": "browse_media_root",
        "label": {
            "en": "Default browsing media category",
            "fr": "Catégorie de navigation par défaut",
        },
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "favorites_in_root",
        "label": {
            "en": "Show favorites directly in the browse root",
            "fr": "Afficher les favoris directement dans la racine de navigation",
            "de": "Favoriten direkt im Browse-Hauptmenü anzeigen",
        },
    },
    {
        "field": {
            "dropdown": {
                "value": "title",
                "items": KODI_BROWSING_SORT[KodiObjectType.MOVIE],
            }
        },
        "id": "browsing_video_sort",
        "label": {
            "en": "Sorting method for video browsing",
            "fr": "Méthode de tri pour la navigation vidéo",
        },
    },
    {
        "field": {
            "dropdown": {
                "value": "album",
                "items": KODI_BROWSING_SORT[KodiObjectType.ALBUM],
            }
        },
        "id": "browsing_album_sort",
        "label": {
            "en": "Sorting method for albums browsing",
            "fr": "Méthode de tri pour la navigation des albums",
        },
    },
    {
        "field": {
            "dropdown": {
                "value": "",
                "items": KODI_BROWSING_SORT[KodiObjectType.FILE],
            }
        },
        "id": "browsing_files_sort",
        "label": {
            "en": "Sorting method for files browsing",
            "fr": "Méthode de tri pour la navigation de fichiers",
        },
    },
    {
        "field": {"checkbox": {"value": True}},
        "id": "show_stream_name",
        "label": {
            "en": "Show audio/subtitle track name",
            "fr": "Afficher le nom de la piste audio/sous-titres",
        },
    },
    {
        "field": {"checkbox": {"value": True}},
        "id": "show_stream_language_name",
        "label": {
            "en": "Show language name instead of track name",
            "fr": "Afficher le nom de la langue au lieu du nom de la piste",
        },
    },
    {
        "field": {"checkbox": {"value": True}},
        "id": "media_update_task",
        "label": {"en": "Enable media update task", "fr": "Activer la tâche de mise à jour du média"},
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "download_artwork",
        "label": {
            "en": "Download artwork instead of transmitting URL to the remote",
            "fr": "Télécharger l'image au lieu de transmettre l'URL à la télécommande",
        },
    },
    {
        "field": {"number": {"value": 12, "min": 5, "max": 60, "steps": 1, "unit": {"en": "s", "fr": "s"}}},
        "id": "artwork_timeout_seconds",
        "label": {
            "en": "Artwork download timeout (seconds, only used when downloading artwork)",
            "fr": "Délai de téléchargement de l'image (secondes, utilisé uniquement avec téléchargement)",
        },
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "disable_keyboard_map",
        "label": {
            "en": "Disable keyboard map : check only if some commands fail (eg arrow keys)",
            "fr": "Désactiver les commandes clavier : cocher uniquement si certaines commandes échouent "
            "(ex : commandes de direction)",
        },
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "suppress_volume_overlay",
        "label": {
            "en": "(Deprecated — no longer has any effect; setting retained for config backward compatibility) "
            "Suppress volume overlay on remote",
            "fr": "(Obsolète — sans effet ; paramètre conservé pour compatibilité ascendante) "
            "Masquer l'indicateur de volume sur la telecommande",
        },
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "video_only_browse_filter",
        "label": {
            "en": "Video-only browse (hide music, pictures, and subtitle/nfo files)",
            "fr": "Navigation vidéo uniquement (masquer musique, images et fichiers nfo/sous-titres)",
        },
    },
    {
        "field": {"checkbox": {"value": False}},
        "id": "suppress_unsupported_command_errors",
        "label": {
            "en": "Suppress Kodi command errors (hides 'not supported' notifications, e.g. pause on live TV)",
            "fr": "Masquer les erreurs de commande Kodi (masque les notifications 'non supporté', "
            "par ex. pause sur TV en direct)",
        },
    },
    {
        "field": {
            "dropdown": {
                "value": next(iter(KODI_POWEROFF_COMMANDS)),
                "items": [{"id": key, "label": value} for key, value in KODI_POWEROFF_COMMANDS.items()],
            }
        },
        "id": "power_off_command",
        "label": {
            "en": "Power off command",
            "fr": "Commande d'arrêt",
        },
    },
]
