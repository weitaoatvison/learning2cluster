import matplotlib
matplotlib.use('Agg')

import numpy as np

from keras.layers.advanced_activations import LeakyReLU
from keras.optimizers import Adadelta

from random import randint
from time import time

from impl.nn.try00.cluster_nn_try00_v51 import ClusterNNTry00_V51

if __name__ == '__main__':

    # Difference to test_cluster_nn_try00.py: No embedding is used and the network always returns that 10 clusters were
    # found, but some of them may be empty

    from sys import platform

    from impl.data.simple_2d_point_data_provider import Simple2DPointDataProvider
    from impl.nn.base.embedding_nn.cnn_embedding import CnnEmbedding

    is_linux = platform == "linux" or platform == "linux2"
    top_dir = "/cluster/home/meierbe8/data/MT/" if is_linux else "G:/tmp/"
    ds_dir = "./" if is_linux else "../"

    dp = Simple2DPointDataProvider(
        min_cluster_count=1, max_cluster_count=5, allow_less_clusters=False, use_extended_data_gen=True
    )
    en = None

    c_nn = ClusterNNTry00_V51(dp, 72, en, lstm_layers=7, internal_embedding_size=96, cluster_count_dense_layers=1, cluster_count_dense_units=256,
                              output_dense_layers=1, output_dense_units=256, cluster_count_lstm_layers=1, cluster_count_lstm_units=128,
                              kl_embedding_size=128, kl_divergence_factor=0.1)
    c_nn.include_self_comparison = False
    c_nn.weighted_classes = True
    c_nn.class_weights_approximation = 'stochastic'
    c_nn.minibatch_size = 200
    c_nn.class_weights_post_processing_f = lambda x: np.sqrt(x)
    c_nn.set_loss_weight('similarities_output', 5.0)
    c_nn.optimizer = Adadelta(lr=5.0)

    validation_factor = 10
    c_nn.early_stopping_iterations = 10001
    c_nn.validate_every_nth_epoch = 10 * validation_factor
    c_nn.validation_data_count = c_nn.minibatch_size * validation_factor
    # c_nn.prepend_base_name_to_layer_name = False
    print_loss_plot_every_nth_itr = 100

    # c_nn.f_cluster_count = lambda: 10
    # c_nn.minibatch_size = 200

    # c_nn._get_keras_loss()

    # i = 0
    # start = time()
    # while True:
    #     try:
    #         print(i)
    #         c = dp.get_data(50, 200)
    #         print("Min cluster count: {}, Max cluster count: {}".format(min(map(len, c)), max(map(len, c))))
    #         now = time()
    #         i += 1
    #         print("Avg: {}".format((now - start) / i))
    #     except:
    #         print("ERROR")

    c_nn.build_networks(print_summaries=False)

    # Enable autosave and try to load the latest configuration
    autosave_dir = top_dir + '/autosave_ClusterNNTry00_V57'
    c_nn.register_autosave(autosave_dir, example_count=10, nth_iteration=500, train_examples_nth_iteration=2000, print_loss_plot_every_nth_itr=print_loss_plot_every_nth_itr)
    c_nn.try_load_from_autosave(autosave_dir)

    # Train a loooong time
    c_nn.train(1000000)

    # Load the best weights and create some examples
    c_nn.try_load_from_autosave(autosave_dir, config='best')
    c_nn.test_network(count=30, output_directory=autosave_dir + '/examples_final', data_type='test', create_date_dir=False)


