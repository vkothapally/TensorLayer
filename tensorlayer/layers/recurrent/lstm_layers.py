#! /usr/bin/python
# -*- coding: utf-8 -*-

import tensorflow as tf

from tensorflow.python.ops import array_ops

from tensorlayer.layers.core import Layer
from tensorlayer.layers.recurrent.lstm_cells import BasicConvLSTMCell

from tensorlayer import logging

from tensorlayer.decorators import auto_parse_inputs
from tensorlayer.decorators import deprecated_alias
from tensorlayer.decorators import deprecated_args


class ConvLSTMLayer(Layer):
    """A fixed length Convolutional LSTM layer.

    See this `paper <https://arxiv.org/abs/1506.04214>`__ .

    Parameters
    ----------
    prev_layer : :class:`Layer`
        Previous layer
    cell_shape : tuple of int
        The shape of each cell width * height
    filter_size : tuple of int
        The size of filter width * height
    cell_fn : a convolutional RNN cell
        Cell function like :class:`BasicConvLSTMCell`
    feature_map : int
        The number of feature map in the layer.
    initializer : initializer
        The initializer for initializing the parameters.
    n_steps : int
        The sequence length.
    initial_state : None or ConvLSTM State
        If None, `initial_state` is zero state.
    return_last : boolean
        Whether return last output or all outputs in each step.
            - If True, return the last output, "Sequence input and single output".
            - If False, return all outputs, "Synced sequence input and output".
            - In other word, if you want to stack more RNNs on this layer, set to False.
    return_seq_2d : boolean
        Only consider this argument when `return_last` is `False`
            - If True, return 2D Tensor [n_example, n_hidden], for stacking DenseLayer after it.
            - If False, return 3D Tensor [n_example/n_steps, n_steps, n_hidden], for stacking multiple RNN after it.
    name : str
        A unique layer name.

    Attributes
    ----------
    outputs : tensor
        The output of this RNN. return_last = False, outputs = all cell_output, which is the hidden state.
        cell_output.get_shape() = (?, h, w, c])

    final_state : tensor or StateTuple
        The finial state of this layer.
            - When state_is_tuple = False, it is the final hidden and cell states,
            - When state_is_tuple = True, You can get the final state after each iteration during training, then feed it to the initial state of next iteration.

    initial_state : tensor or StateTuple
        It is the initial state of this ConvLSTM layer, you can use it to initialize
        your state at the beginning of each epoch or iteration according to your
        training procedure.

    batch_size : int or tensor
        Is int, if able to compute the batch_size, otherwise, tensor for ``?``.

    """

    @deprecated_alias(
        layer='prev_layer', end_support_version="2.0.0"
    )  # TODO: remove this line before releasing TL 2.0.0
    @deprecated_args(
        end_support_version="2.1.0",
        instructions="`prev_layer` is deprecated, use the functional API instead",
        deprecated_args=("prev_layer", ),
    )  # TODO: remove this line before releasing TL 2.1.0
    def __init__(
        self,
        prev_layer,
        cell_shape=None,
        feature_map=1,
        filter_size=(3, 3),
        cell_fn=BasicConvLSTMCell,
        initializer=tf.random_uniform_initializer(-0.1, 0.1),
        n_steps=5,
        initial_state=None,
        return_last=False,
        return_seq_2d=False,
        name='convlstm',
    ):
        super(ConvLSTMLayer, self).__init__(prev_layer=prev_layer, name=name)

        logging.info(
            "ConvLSTMLayer %s: feature_map: %d, n_steps: %d, "
            "in_dim: %d %s, cell_fn: %s " % (
                self.name, feature_map, n_steps, self._temp_data['inputs'].get_shape().ndims,
                self._temp_data['inputs'].get_shape(), cell_fn.__name__
            )
        )
        # You can get the dimension by .get_shape() or ._shape, and check the
        # dimension by .with_rank() as follow.
        # self._temp_data['inputs'].get_shape().with_rank(2)
        # self._temp_data['inputs'].get_shape().with_rank(3)

        # Input dimension should be rank 5 [batch_size, n_steps(max), h, w, c]
        try:
            self._temp_data['inputs'].get_shape().with_rank(5)
        except Exception:
            raise Exception(
                "RNN : Input dimension should be rank 5 : [batch_size, n_steps, input_x, "
                "input_y, feature_map]"
            )

        fixed_batch_size = self._temp_data['inputs'].get_shape().with_rank_at_least(1)[0]

        if fixed_batch_size.value:
            batch_size = fixed_batch_size.value
            logging.info("     RNN batch_size (concurrent processes): %d" % batch_size)

        else:
            batch_size = array_ops.shape(self._temp_data['inputs'])[0]
            logging.info("     non specified batch_size, uses a tensor instead.")
        self.batch_size = batch_size
        outputs = []
        self.cell = cell = cell_fn(shape=cell_shape, filter_size=filter_size, num_features=feature_map)

        if initial_state is None:
            self.initial_state = cell.zero_state(batch_size, dtype=self._temp_data['inputs'].dtype)
        else:
            self.initial_state = initial_state

        state = self.initial_state

        # with tf.variable_scope("model", reuse=None, initializer=initializer):
        with tf.variable_scope(name, initializer=initializer) as vs:
            for time_step in range(n_steps):
                if time_step > 0: tf.get_variable_scope().reuse_variables()
                (cell_output, state) = cell(self._temp_data['inputs'][:, time_step, :, :, :], state)
                outputs.append(cell_output)

            # Retrieve just the RNN variables.
            # rnn_variables = [v for v in tf.all_variables() if v.name.startswith(vs.name)]
            rnn_variables = tf.get_collection(tf.GraphKeys.VARIABLES, scope=vs.name)

            logging.info(" n_params : %d" % (len(rnn_variables)))

            if return_last:
                # 2D Tensor [batch_size, n_hidden]
                self._temp_data['outputs'] = outputs[-1]
            else:
                if return_seq_2d:
                    # PTB tutorial: stack dense layer after that, or compute the cost from the output
                    # 4D Tensor [n_example, h, w, c]
                    self._temp_data['outputs'] = tf.reshape(
                        tf.concat(outputs, 1),
                        [-1, cell_shape[0] * cell_shape[1] * feature_map]
                    )
                else:
                    # <akara>: stack more RNN layer after that
                    # 5D Tensor [n_example/n_steps, n_steps, h, w, c]
                    self._temp_data['outputs'] = tf.reshape(
                        tf.concat(outputs, 1),
                        [-1, n_steps, cell_shape[0], cell_shape[1], feature_map]
                    )

        self.final_state = state