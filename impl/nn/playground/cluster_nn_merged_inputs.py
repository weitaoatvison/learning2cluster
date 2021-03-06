import numpy as np

from time import time

from keras.layers.normalization import BatchNormalization
from keras.layers import Reshape, Concatenate, Bidirectional, LSTM, Dense, Activation

from core.nn.helper import slice_layer
from impl.nn.base.simple_loss.simple_loss_cluster_nn_v02 import SimpleLossClusterNN_V02

class ClusterNNMergedInputs(SimpleLossClusterNN_V02):
    """
    This minimal cluster NN is just a test implementation. It is very minimal and therefore can be used as a simple
    example for a clustering network.
    """

    def __init__(self, data_provider, input_count, embedding_nn=None, weighted_classes=False):
        super().__init__(data_provider, input_count, embedding_nn, weighted_classes, include_input_count_in_name=False)

    def _build_network(self, network_input, network_output, additional_network_outputs):
        cluster_counts = list(self.data_provider.get_cluster_counts())

        # The simple loss cluster NN requires a specific output: a list of softmax distributions
        # First in this list are all softmax distributions for k=k_min for each object, then for k=k_min+1 for each
        # object etc. At the end, there is the cluster count output.

        # First we get an embedding for the network inputs
        print("Get embeddings")
        t_start = time()
        embeddings = self._get_embedding(network_input, time_distributed=True)
        t_end = time()
        print("Got all embeddings. Required time: {}".format(t_end - t_start))

        # Reshape all embeddings to 1d vectors
        embedding_shape = embeddings[0].shape
        embedding_size = int(str(np.prod(embedding_shape[1:])))
        embedding_reshaper = self._s_layer('embedding_reshape', lambda name: Reshape((1, embedding_size), name=name))
        embeddings_reshaped = [embedding_reshaper(embedding) for embedding in embeddings]

        # Merge all embeddings to one tensor
        embeddings_merged = self._s_layer('embeddings_merge', lambda name: Concatenate(axis=1, name=name))(embeddings_reshaped)

        # Use now one LSTM-layer to process all embeddings
        lstm_units = embedding_size * 4
        processed = self._s_layer('LSTM_proc_0', lambda name: Bidirectional(LSTM(lstm_units, return_sequences=True), name=name))(embeddings_merged)

        # Split the tensor to seperate layers
        embeddings_processed = [self._s_layer('slice_{}'.format(i), lambda name: slice_layer(processed, i, name)) for i in range(len(network_input))]

        # Create now two outputs: The cluster count and for each cluster count / object combination a softmax distribution.
        # These outputs are independent of each other, therefore it doesn't matter which is calculated first. Let us start
        # with the cluster count / object combinations.

        # First prepare some generally required layers
        output_dense_size = embedding_size * 10
        layers = [
            self._s_layer('output_dense0', lambda name: Dense(output_dense_size, name=name)),
            self._s_layer('output_batch0', lambda name: BatchNormalization(name=name)),
            self._s_layer('output_relu0', lambda name: Activation('relu', name=name))
        ]
        cluster_softmax = {
            k: self._s_layer('softmax_cluster_{}'.format(k), lambda name: Dense(k, activation='softmax', name=name)) for k in cluster_counts
        }

        # Create now the outputs
        clusters_output = additional_network_outputs['clusters'] = {}
        for i in range(len(embeddings_processed)):
            embedding_proc = embeddings_processed[i]

            # Add the required layers
            for layer in layers:
                embedding_proc = layer(embedding_proc)

            input_clusters_output = clusters_output['input{}'.format(i)] = {}
            for k in cluster_counts:

                # Create now the required softmax distributions
                output_classifier = cluster_softmax[k](embedding_proc)
                input_clusters_output['cluster{}'.format(k)] = output_classifier
                network_output.append(output_classifier)

        # Calculate the real cluster count
        cluster_count_dense_units = embedding_size * 8
        cluster_count = self._s_layer('cluster_count_LSTM_merge', lambda name: Bidirectional(LSTM(lstm_units), name=name)(embeddings_merged))
        cluster_count = self._s_layer('cluster_count_dense0', lambda name: Dense(cluster_count_dense_units, name=name))(cluster_count)
        cluster_count = self._s_layer('cluster_count_batch0', lambda name: BatchNormalization(name=name))(cluster_count)

        # Add a debug output
        self._add_debug_output(cluster_count, 'cluster_count')

        cluster_count = self._s_layer('cluster_count_relu0', lambda name: Activation('relu', name=name))(cluster_count)

        # The next layer is an output-layer, therefore the name must not be formatted
        cluster_count = self._s_layer(
            'cluster_count_output',
            lambda name: Dense(len(cluster_counts), activation='softmax', name=name),
            format_name=False
        )(cluster_count)
        additional_network_outputs['cluster_count_output'] = cluster_count

        network_output.append(cluster_count)

        return True

