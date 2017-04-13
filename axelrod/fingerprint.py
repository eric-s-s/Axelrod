from collections import namedtuple
from tempfile import NamedTemporaryFile
from typing import Any
import matplotlib.pyplot as plt
import numpy as np
import tqdm
import axelrod as axl

from axelrod import on_windows, Player
from axelrod.strategy_transformers import JossAnnTransformer, DualTransformer
from axelrod.interaction_utils import (
    compute_final_score_per_turn, read_interactions_from_file)


Point = namedtuple('Point', 'x y')


class AshlockFingerprint(object):
    def __init__(self, strategy: Any, probe: Any = axl.TitForTat,
                 step: float = 0.01, progress_bar: bool = True) -> None:
        """
        Parameters
        ----------
        strategy : class or instance
            A class that must be descended from axelrod.Player or an instance of
            axelrod.Player.
        probe : class or instance
            A class that must be descended from axelrod.Player or an instance of
            axelrod.Player.
            Default: Tit For Tat
        step: float = 0.01
            The separation between each Point. Smaller steps will
            produce more Points that will be closer together.
        progress_bar: bool = True
            True = show a progress bar when constructing probes and running
            tournament.
        """
        self.player = create_player(strategy)
        self._probe_class, self._probe_kwargs = get_class_and_kwargs(probe)
        self._step = step
        self.progress_bar = progress_bar
        self.points = self._create_points()
        self._probe_list = self._create_probes()

        self.interactions = {}  # type: dict
        self.spatial_tournament = None  # type: axl.SpatialTournament
        self.data = {}  # type: dict

    @property
    def step(self):
        return self._step

    @step.setter
    def step(self, new_step: float):
        self._step = new_step
        self.points = self._create_points()
        self._probe_list = self._create_probes()

    @property
    def probe(self):
        return self._probe_class(**self._probe_kwargs)

    @probe.setter
    def probe(self, new_probe):
        self._probe_class, self._probe_kwargs = get_class_and_kwargs(new_probe)
        self._probe_list = self._create_probes()

    def _create_points(self) -> list:
        """Returns a list of Points(x=0.0-1.0, y=0.0-1.0) at
        intervals=self._step. self._step=0.1 produces the list
        [Point(0.0, 0.0), Point(0.1, 0.0), ... Point(1.0, 0.9), Point(1.0, 1.0)]
        """
        points_per_side = int(1 / self._step) + 1
        points = []
        for x in np.linspace(0, 1, points_per_side):
            for y in np.linspace(0, 1, points_per_side):
                points.append(Point(x, y))
        return points

    def _create_probes(self):
        """Creates a list of probe strategies over the unit square.

        Constructs probe strategies that correspond to points with coordinates
        (x, y). The probes are created using the `JossAnnTransformer` and
        `DualTransformer`."""
        if self.progress_bar:
            points = tqdm.tqdm(self.points, desc="Generating probes")
        else:
            points = self.points
        probes = [self._create_jossann(point) for point in points]
        return probes

    def _create_jossann(self, point):
        """Creates a JossAnn probe player that matches the Point.

        If the coordinates of point sums to more than 1 the parameters are
        flipped and subtracted from 1 to give meaningful probabilities. We also
        use the Dual of the probe. This is outlined further in [Ashlock2010]_.
        """
        x, y = point

        if x + y >= 1:
            joss_ann = DualTransformer()(
                JossAnnTransformer((1 - x, 1 - y))(self._probe_class)
            )(**self._probe_kwargs)
        else:
            joss_ann = JossAnnTransformer((x, y))(
                self._probe_class
            )(**self._probe_kwargs)
        return joss_ann

    def fingerprint(self, turns: int = 50, repetitions: int = 10,
                    new_step: float = None, processes: int = None,
                    filename: str = None, in_memory: bool =False) -> dict:
        """Build and play the spatial tournament.

        Creates the probes and their edges then builds a spatial tournament.
        When the coordinates of the probe sum to more than 1, the dual of the
        probe is taken instead and then the Joss-Ann Transformer is applied. If
        the coordinates sum to less than 1 (or equal), then only the Joss-Ann is
        applied, a dual is not required.

        Parameters
        ----------
        turns : integer, optional
            The number of turns per match
        repetitions : integer, optional
            The number of times the round robin should be repeated
        new_step : float, optional
            The separation between each Point. Smaller steps will
            produce more Points that will be closer together.
        processes : integer, optional
            The number of processes to be used for parallel processing
        filename : str
            File where results are saved.
        in_memory : bool

        Returns
        ----------
        self.data : dictionary
            A dictionary where the keys are coordinates of the form (x, y) and
            the values are the mean score for the corresponding interactions.
        """

        if on_windows and filename is None:  # pragma: no cover
            in_memory = True
        elif filename is None:
            output_file = NamedTemporaryFile(mode='w')
            filename = output_file.name

        if new_step:
            self.step = new_step

        tourn_players = [self.player] + self._probe_list
        edges = [(0, probe_index) for probe_index in
                 range(1, len(self._probe_list) + 1)]

        self.spatial_tournament = axl.SpatialTournament(
            tourn_players,
            turns=turns,
            repetitions=repetitions,
            edges=edges
        )
        self.spatial_tournament.play(build_results=False,
                                     filename=filename,
                                     processes=processes,
                                     in_memory=in_memory,
                                     progress_bar=self.progress_bar)
        if in_memory:
            self.interactions = self.spatial_tournament.interactions_dict
        else:
            self.interactions = read_interactions_from_file(
                filename, progress_bar=self.progress_bar)

        self.data = self._generate_data(edges)
        return self.data

    def _generate_data(self, edges: list) -> dict:
        """Generates useful data from a spatial tournament.

        Matches interactions from `results` to their corresponding Point in
        `probe_points`.

        Returns
        ----------
        point_scores : dictionary
            A dictionary where the keys are Points of the form (x, y) and
            the values are the mean score for the corresponding interactions.
        """
        edge_scores = [
            np.mean(
                [compute_final_score_per_turn(scores)[0]
                 for scores in self.interactions[edge]]
            ) for edge in edges
        ]
        point_scores = dict(zip(self.points, edge_scores))
        return point_scores

    def plot(self, col_map='seismic', interpolation='none', title=None,
             colorbar=True, labels=True):
        """Plot the results of the spatial tournament.

        Parameters
        ----------
        col_map : str, optional
            A matplotlib colour map, full list can be found at
            http://matplotlib.org/examples/color/colormaps_reference.html
        interpolation : str, optional
            A matplotlib interpolation, full list can be found at
            http://matplotlib.org/examples/images_contours_and_fields/interpolation_methods.html
        title : str, optional
            A title for the plot
        colorbar : bool, optional
            Choose whether the colorbar should be included or not
        labels : bool, optional
            Choose whether the axis labels and ticks should be included

        Returns
        ----------
        figure : matplotlib figure
            A heat plot of the results of the spatial tournament
        """

        plotting_data = self._reshape_data()
        fig, ax = plt.subplots()
        cax = ax.imshow(
            plotting_data, cmap=col_map, interpolation=interpolation)

        if colorbar:
            max_score = max(self.data.values())
            min_score = min(self.data.values())
            ticks = [min_score, (max_score + min_score) / 2, max_score]
            fig.colorbar(cax, ticks=ticks)

        plt.xlabel('$x$')
        plt.ylabel('$y$', rotation=0)
        ax.tick_params(axis='both', which='both', length=0)
        plt.xticks([0, len(plotting_data) - 1], ['0', '1'])
        plt.yticks([0, len(plotting_data) - 1], ['1', '0'])

        if not labels:
            plt.axis('off')

        if title is not None:
            plt.title(title)
        return fig

    def _reshape_data(self):
        """Shape the data so that it can be plotted easily.

        Returns
        ----------
        plotting_data : list
            2-D numpy array of the scores, correctly shaped to ensure that the
            score corresponding to Point (0, 0) is in the left hand corner ie.
            the standard origin.
        """
        side_len = int(1 / self._step) + 1
        ordered_data = [self.data[point] for point in self.points]
        shaped_data = np.reshape(ordered_data, (side_len, side_len), order='F')
        plotting_data = np.flipud(shaped_data)
        return plotting_data


def get_class_and_kwargs(strategy_or_player: Any) -> tuple:
    """If strategy, returns a class and kwargs to create default player.
    If Player, returns a class and kwargs to re-create that instance."""
    probe_player = create_player(strategy_or_player)
    return probe_player.__class__, probe_player.init_kwargs


def create_player(strategy_or_player: Any) -> Player:
    """If strategy, returns the default Player of that strategy. Else
    returns the Player."""
    if isinstance(strategy_or_player, axl.Player):
        return strategy_or_player.clone()
    return strategy_or_player()
