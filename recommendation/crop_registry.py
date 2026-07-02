CROP_REGISTRY = {

    "Andhra Pradesh": {

        "West Godavari": {
            "rice",
            "banana",
            "coconut",
            "maize",
            "sugarcane",
            "blackgram",
            "mungbean",
            "papaya",
            "mango"
        },

        "East Godavari": {
            "rice",
            "banana",
            "coconut",
            "maize",
            "sugarcane",
            "papaya",
            "mango"
        },

        "Krishna": {
            "rice",
            "maize",
            "cotton",
            "blackgram",
            "sugarcane"
        }
    },

    "Himachal Pradesh": {

        "Shimla": {
            "apple",
            "pear",
            "plum",
            "potato",
            "maize"
        },

        "Kullu": {
            "apple",
            "pear",
            "plum",
            "potato",
            "maize"
        }
    }
}

STATE_FALLBACK = {

    "Andhra Pradesh": {
        "rice",
        "banana",
        "coconut",
        "maize",
        "sugarcane",
        "cotton",
        "papaya",
        "mango",
        "blackgram",
        "mungbean"
    },

    "Himachal Pradesh": {
        "apple",
        "pear",
        "plum",
        "potato",
        "maize",
        "wheat"
    }
}


def get_allowed_crops(state, district):

    if not state:
        return None

    if state in CROP_REGISTRY:

        district_map = CROP_REGISTRY[state]

        if district and district in district_map:
            return district_map[district]

        return STATE_FALLBACK.get(state)

    return None