"""Name normalisation shared by skill identity and evidence keys."""
import unicodedata


def normalized_name(name):
    return ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()
