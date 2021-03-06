# TODO
# Requirements:
# - Output can be a 2D image
# - Output can be a 1D image
# - Allow different audio data types (spectrogram types; maybe use the AUdioHelper from VT2 as an argument for the audio data provider)
import numpy as np
from random import Random
from os import path
from time import time
from math import ceil

from impl.data.image.image_data_provider import ImageDataProvider

from impl.data.misc.audio_helper import AudioHelper

from impl.misc.simple_file_cache import SimpleFileCache

class AudioDataProvider(ImageDataProvider):
    def __init__(self, data_dir=None, audio_helper=None, cache_directory=None, train_classes=None, validate_classes=None,
                 test_classes=None, window_width=100, return_1d_audio_data=False,
                 min_cluster_count=None, max_cluster_count=None, concat_audio_files_of_speaker=False,
                 minimum_snippets_per_cluster=1, return_equal_snippet_size=True, split_audio_pieces_longer_than_and_create_hints=None,
                 snippet_merge_mode=None):
        # snippet_merge_mode:
        # This is a list of a file count. E.g. if it is [8, 2] then the first two files of a speaker (ordered by the
        # filenames) are merged to one snippet and the next two files are merged to a second snippet. The value
        # -1 might be used at the end of the list to incidcate that all other snippets should be merged into a final
        # new snippet. If -1 is not given, the additional snippets will be ignored.
        # If snippet_merge_mode is not None, the "concat_audio_files_of_speaker" setting will be ignored. Its behavior
        # can be produced with "snippet_merge_mode=[-1]", therefore, it is obsolete (it is still there for compatibility).

        if audio_helper is None:
            audio_helper = AudioHelper()

        self.__rand = Random()
        self.__data = None
        self.__data_dir = data_dir
        self.__audio_helper = audio_helper
        self.__cache = None if cache_directory is None else SimpleFileCache(cache_directory, compression=True)
        self.__concat_audio_files_of_speaker = concat_audio_files_of_speaker
        self.__snippet_merge_mode = snippet_merge_mode
        self.__split_modes = {}

        # Window width may be a scalar or an array of possible intervals for the sizes, e.g.:
        # [(180, 200), (400, 420), ...]
        # The output shape will be the maximum possible window width
        self.__window_width = [(window_width, window_width)] if isinstance(window_width, int) else window_width

        # The minimum amount of snippets per cluster. For the "default" behaviour just 1 can be chosen.
        # In general it is possible to use a natural number. It is also possible to use a list with windows
        # widths where each cluster at least contains snippets with windows in the given interval. E.g.:
        # [(100, 200), (500, 550), ...]
        # This feature may be used to force a cluster to contains at least e.g. one small and one large element.
        self.__minimum_snippets_per_cluster = minimum_snippets_per_cluster

        # Should it be allowed that snippets which are generated by the __minimum_snippets_per_cluster setting
        # overlap? This setting is only used if "__concat_audio_files_of_speaker" is enabled
        self.__allow_minimum_snippets_overlap = False

        # If "return_equal_snippet_size" is False different snippets may have different lengths
        self.__return_equal_snippet_size = return_equal_snippet_size

        # If this setting is None it is not used. If it is not None it has to be a positive integer. The effect is then
        # the following: Each generated audio snippet that is longer than this defined value will be split into smaller
        # pieces and the "hint" mechanism is used to return "hints" that these snippets belong together.
        self.__split_audio_pieces_longer_than_and_create_hints = split_audio_pieces_longer_than_and_create_hints

        # The output length is the maximum possible snippet length
        self.__output_length = max(map(lambda r: r[1], self.__window_width + ([] if isinstance(self.__minimum_snippets_per_cluster, int) else self.__minimum_snippets_per_cluster)))
        if self.__split_audio_pieces_longer_than_and_create_hints is not None:
            self.__output_length = min(self.__split_audio_pieces_longer_than_and_create_hints, self.__output_length)

        self._load_data()

        if train_classes is None and validate_classes is None and test_classes is None:
            rand = Random()
            rand.seed(1337)
            classes = list(self.__data.keys())
            rand.shuffle(classes)
            train_classes_count = int(0.8 * len(classes))
            train_classes = classes[:train_classes_count]
            validate_classes = classes[train_classes_count:]
            test_classes = classes[train_classes_count:]
        if test_classes is not None and validate_classes is not None and train_classes is None:
            classes = list(self.__data.keys())
            train_classes = set(classes)
            train_classes -= set(test_classes)
            train_classes -= set(validate_classes)
            train_classes = list(train_classes)

        super().__init__(
            train_classes=train_classes, validate_classes=validate_classes, test_classes=test_classes,
            auto_load_data=True, return_1d_images=return_1d_audio_data, min_cluster_count=min_cluster_count,
            max_cluster_count=max_cluster_count,
            min_element_count_per_cluster=minimum_snippets_per_cluster if isinstance(minimum_snippets_per_cluster, int) else len(minimum_snippets_per_cluster)
        )

    def set_split_mode(self, data_type, mode=None):
        if mode is not None:
            # Currently, there is only one valid mode; maybe in futture there will be more different modes
            if mode not in ['snippet']:
                return False
        self.__split_modes[data_type] = mode

    def get_split_mode(self, data_type):
        if data_type in self.__split_modes:
            return self.__split_modes[data_type]
        return None

    def get_required_input_count_for_full_test(self, data_type='test'):
        if len(self.__window_width) != 1 or (self.__window_width[0][0] != self.__window_width[0][1]):
            raise Exception("It is required that only one constant possible window width exists if the required inputs should be calculated.")
        classes = self._data_classes[data_type]
        window_width = self.__window_width[0][0]
        def required_input_count_for_snippet(x):
            return int(ceil(x['content'].shape[0] / window_width))
        input_count = sum(map(
            lambda cls: sum(map(
                lambda snippet: required_input_count_for_snippet(snippet),
                self.__data[cls]
            )),
            classes
        ))
        return input_count

    def _get_img_data_shape(self):

        # If "return_equal_snippet_size" is False, then just an upper-bound is returned
        return (self.__output_length, self.__audio_helper.get_default_spectrogram_coefficients_count(), 1)

    def __get_cache_key(self, path):
        return "[{}]_[{}]".format(self.__audio_helper.get_settings_str(), path)

    def __load_audio_file(self, path):
        cache_key = self.__get_cache_key(path)
        if self.__cache is not None and self.__cache.exists(cache_key):
            print("Load {} from the cache...".format(path))
            return self.__cache.load(cache_key)
        print("Load {}...".format(path))
        content = self.__audio_helper.audio_to_default_spectrogram(path)
        content = np.transpose(content)
        content = np.reshape(content, content.shape + (1,))
        if self.__cache is not None:
            self.__cache.save(cache_key, content)
        return content

    def _load_data(self):
        if self.__data is None:
            clusters = self._get_audio_file_clusters(self.__data_dir)
            output_clusters = {}
            t_start = time()
            min_snippet_length = max(map(lambda r: r[0], self.__window_width))
            for k in clusters.keys():

                # Get all audio snippets
                snippets = list(map(
                    lambda file: {
                        'content': self.__load_audio_file(path.join(self.__data_dir, file)),
                        'filename': path.splitext(path.basename(path.join(self.__data_dir, file)))[0]
                    },
                    sorted(clusters[k])
                ))

                if self.__snippet_merge_mode is not None:

                    # Merge the snippets according to the defined configuration
                    new_snippets = []
                    i = 0
                    for merge_len in self.__snippet_merge_mode:

                        # Get the start and end index
                        start = i
                        if merge_len == -1:
                            if start >= len(snippets):
                                break
                            end = len(snippets)
                        else:
                            end = start + merge_len

                        # Merge the snippets
                        source_snippets = list(map(lambda x: x['content'], snippets[start:end]))
                        if len(source_snippets) > 0:
                            new_snippets.append({
                                'content': np.concatenate(source_snippets),
                                'filename': 'CONCAT({}:{})'.format(start, end)
                            })
                        i += (end - start)
                    snippets = new_snippets

                elif self.__concat_audio_files_of_speaker:

                    # Merge all snippets to one large snippet
                    snippets = [{
                        'content': np.concatenate(list(map(lambda x: x['content'], snippets))),
                        'filename': 'CONCAT'
                    }]

                # Filter the snippets for the minimum length
                snippets = list(filter(
                    lambda snippet: snippet['content'].shape[0] >= min_snippet_length,
                    snippets
                ))

                if len(snippets) == 0:
                    print("WARNING: All input files for the class '{}' are to short (the length must be 1s or more). This class is ignored.".format(k))
                else:
                    output_clusters[k] = snippets
            t_end = time()
            t_delta = t_end - t_start
            print("Required {} seconds to load the data...".format(t_delta))
            self.__data = output_clusters
        return self.__data

    def _get_audio_file_clusters(self, data_dir):
        return {}

    def _get_random_element(self, class_name, data_type, element_index=None):#, window_range=None, blocked_ranges=None):
        if data_type is not None and data_type in self.__split_modes and self.__split_modes[data_type] is not None:
            mode = self.__split_modes[data_type]
        else:
            mode = None

        # Get a target audio object
        audio_objects = self._get_data()[class_name]

        if mode == 'snippet' and element_index is not None and len(audio_objects) > element_index:
            audio_object = audio_objects[element_index]
        else:
            audio_object = self.__rand.choice(audio_objects)
        audio_content = audio_object['content']
        audio_width = audio_content.shape[0]

        # Get all non-blocked ranges (this results in a list of ranges)
        # if blocked_ranges is None:
        #     ranges = [(0, audio_width)]
        # else:
        #     pass

        # Choose a possible window width
        # if window_range is None:
        if (not isinstance(self.__minimum_snippets_per_cluster, int)) and element_index < len(self.__minimum_snippets_per_cluster):
            window_range = self.__minimum_snippets_per_cluster[element_index]
        else:
            possible_window_ranges = list(filter(lambda w: (w[1] - w[0]) <= audio_width, self.__window_width))
            window_range = self.__rand.choice(possible_window_ranges)

        if window_range[0] > audio_width:
            raise Exception("Invalid window width (audio is too short)")
        window_range = (window_range[0], min(window_range[1], audio_width))
        window_width = self.__rand.randint(*window_range)
        if mode == 'snippet':

            # For this mode we want to use the complete sentence and create hints that the sentence is really only
            # one single snippet.

            # Is some padding required?
            snippet_count = int(ceil(audio_width / window_width))
            padding = snippet_count * window_width - audio_width
            if padding > 0:
                new_audio_content = np.zeros((audio_width + padding,) + audio_content.shape[1:], dtype=np.float32)
                begin_padding = self.__rand.randint(0, padding)
                new_audio_content[begin_padding:(begin_padding + audio_width)] = audio_content
                audio_content = new_audio_content
            else:
                begin_padding = 0

            # Split now the audio content into many small pieces
            snippets = list(map(
                lambda si: {
                    'additional_obj_info': {
                        'description': '{} [{}] [{}-{}] [{}/{}] [p{}]'.format(class_name, audio_object['filename'], (si * window_width),
                                                                              ((si + 1) * window_width), si, snippet_count, begin_padding),
                        'class': class_name,
                        'sort_key': '{}/{}/{}'.format(class_name, audio_object['filename'], si)
                    },
                    'content': audio_content[(si * window_width):((si + 1) * window_width)]
                }, range(snippet_count)
            ))

            # Prepare now everything for the output
            element = list(map(lambda x: x['content'], snippets))
            additional_obj_info = list(map(lambda x: x['additional_obj_info'], snippets))

        elif mode is None:

            # Select a random snippet
            start_index_range = (0, audio_content.shape[0] - window_width)
            start_index = self.__rand.randint(start_index_range[0], start_index_range[1])

            element = audio_content[start_index:(start_index + window_width)]
            additional_obj_info = {
                'description': '{} [{}] [{}-{}]'.format(class_name, audio_object['filename'], start_index, start_index + window_width),
                'class': class_name,
                'sort_key': '{}/{}'.format(class_name, start_index)
            }

            # It may be required to put the element to a larger array (if uniform length elements are required)
            if self.__return_equal_snippet_size:
                output_length = self.__output_length
                element_length = element.shape[0]
                if element_length < output_length:
                    result = np.zeros((output_length,) + element.shape[1:], dtype=np.float32)
                    start_index = self.__rand.randint(0, output_length - element_length)
                    result[start_index:(start_index + element_length)] = element
                    element = result

            # Test if element has to be split.
            if self.__split_audio_pieces_longer_than_and_create_hints is not None:
                max_len = self.__split_audio_pieces_longer_than_and_create_hints
                parts = int(ceil(element.shape[0] / max_len))
                if parts > 1:

                    # Ok, we have to do the split
                    elements = []
                    for i in range(parts):
                        new_element = element[(max_len * i):(max_len * (i + 1))]
                        if i == parts - 1:
                            # Do padding if required
                            new_element_length = new_element.shape[0]
                            new_element_padded = np.zeros((max_len,) + new_element.shape[1:], dtype=np.float32)
                            start_index = self.__rand.randint(0, max_len - new_element_length)
                            new_element_padded[start_index:(start_index + new_element_length)] = new_element
                            new_element = new_element_padded
                        elements.append(new_element)

                    # Return now all the new objects; modify the additional obj info (for each piece)
                    element = elements
                    new_additional_obj_info = []
                    for i in range(parts):
                        curr_new_additional_obj_info = dict(additional_obj_info)
                        curr_new_additional_obj_info['description'] += ' [{}/{}]'.format(i + 1, parts)
                        new_additional_obj_info.append(curr_new_additional_obj_info)
                    additional_obj_info = new_additional_obj_info
        else:
            raise Exception("Invalid mode '{}' for data type '{}'.".format(mode, data_type))

        return element, additional_obj_info

    def _image_plot_preprocessor(self, img):

        # Sometimes the range is not exactly [0, 1]; fix this
        img = np.minimum(img, 1.)
        img = np.maximum(img, 0.)

        # Swap the first two axes
        return img.swapaxes(0, 1)



