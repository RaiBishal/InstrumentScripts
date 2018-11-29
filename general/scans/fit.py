# -*- coding: utf-8 -*-
"""The Fit module holds the Fit class, which defines common parameters
for fitting routines.  It also contains implementations of some common
fits (i.e. Linear and Gaussian).

"""
from abc import ABCMeta, abstractmethod
from sys import platform
import ctypes
import os
import sys
import numpy as np
from six import add_metaclass
from scipy.special import erf  # pylint: disable=no-name-in-module

if platform == "win32":
    def handler(_):
        """Basic handler for KeyboardInterrupt

    This handler bypasses the Intel handler and prevents Python from
    completely crashing on a Ctrl+C

        """
        try:
            import _thread
        except ImportError:
            import thread as _thread
        _thread.interrupt_main()
        return 1

    BASEPATH = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages", "numpy", "core")
    print(BASEPATH)
    ctypes.CDLL(os.path.join(BASEPATH, "libmmd.dll"))
    ctypes.CDLL(os.path.join(BASEPATH, "libifcoremd.dll"))
    routine = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)(handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(routine, 1)

else:
    os.environ['FOR_DISABLE_CONSOLE_CTRL_HANDLER'] = "T"
# pylint: disable=wrong-import-position
from scipy.optimize import curve_fit, OptimizeWarning  # noqa: E402


@add_metaclass(ABCMeta)
class Fit(object):
    """The Fit class combines the common requirements needed for fitting.
    We need to be able to turn a set of data points into a set of
    parameters, get the simulated curve from a set of parameters, and
    extract usable information from those parameters.
    """

    def __init__(self, degree, title):
        self.degree = degree
        self._title = title

    @abstractmethod
    def fit(self, x, y):  # pragma: no cover
        """The fit function takes arrays of independent and depedentend
        variables.  It returns a set of parameters in a format that is
        convenient for this specific object.

        """
        return lambda i, j: None

    @abstractmethod
    def get_y(self, x, fit):  # pragma: no cover
        """get_y takes an array of independent variables and a set of model
        parameters and returns the expected dependent variables for
        those parameters

        """
        return lambda i, j: None

    @abstractmethod
    def readable(self, fit):  # pragma: no cover
        """Readable turns the implementation specific set of fit parameters
        into a human readable dictionary.

        """
        return lambda i: {}

    def title(self, params):
        """
        Give the title of the fit.

        Parameters
        ==========
        params
          The list of fit method parameters
        """
        # pylint: disable=unused-argument
        return self._title

    def fit_plot_action(self):
        """
        Create a function to be called in a plotting loop
        to live fit the data

        Returns
        -------
        A function to call in the plotting loop
        """
        def action(x, y, axis):
            """Fit and plot the data within the plotting loop

            Parameters
            ----------
            x : Array of Float
              The x positions measured thus far
            y : Array of Float
              The y positions measured thus far
            axis : matplotlib.axis.Axis
              The axis on which to plot

            Returns
            -------
            line : None or dict
                Either None if the fit is not possible or a dict of the fit
                parameters if the fit was performed

            """
            if len(x) < self.degree:
                return None
            plot_x = np.linspace(np.min(x), np.max(x), 1000)
            values = np.array(y.values())
            if len(values.shape) > 1:
                params = []
                for value in values:
                    try:
                        params.append(self.fit(x, value))
                    except RuntimeError:
                        params.append(None)
                        continue
                    fity = self.get_y(plot_x, params[-1])
                    axis.plot(plot_x, fity, "-",
                              label="{} fit".format(self.title(params[-1])))
            else:
                try:
                    params = self.fit(x, values)
                except RuntimeError:
                    return None
                fity = self.get_y(plot_x, params)
                axis.plot(plot_x, fity, "-",
                          label="{} fit".format(self.title(params)))
            axis.legend()
            return params
        return action


class PolyFit(Fit):
    """
    A fitting class for polynomials
    """

    def __init__(self, degree,
                 title=None):
        if title is None:
            title = "Polynomial fit of degree {}".format(degree)
        Fit.__init__(self, degree + 1, title)

    def fit(self, x, y):
        return np.polyfit(x, y, self.degree - 1)

    def get_y(self, x, fit):
        return np.polyval(fit, x)

    def readable(self, fit):
        if self.degree == 2:
            return {"slope": fit[0], "intercept": fit[1]}
        orders = np.arange(self.degree, 0, -1) - 1
        results = {}
        for key, value in zip(orders, fit):
            results["x^{}".format(key)] = value
        return results

    def title(self, params):
        # pylint: disable=arguments-differ
        xs = ["x^{}".format(i) for i in range(1, len(params))]
        xs = ([""] + xs)[::-1]
        terms = ["{:0.3g}".format(t) + i for i, t in zip(xs, params)]
        return self._title + ": $y = " + " + ".join(terms) + "$"


class ExactFit(Fit):
    """
    A class for pulling the exact data points out of a plot
    """

    def __init__(self):
        Fit.__init__(self, np.inf, "Exact Points")

    def fit(self, x, y):
        return (x, y)

    def get_y(self, _, fit):
        return fit[1]

    def readable(self, fit):
        return {"x": fit[0], "y": map(float, fit[1])}

    def title(self, _):
        return "Exact Points"

    def fit_plot_action(self):
        def action(x, y, _):
            """Perform no actual plotting action and simply pass on the data
 points.

            """
            return (x, y)
        return action


class PeakFit(Fit):
    """A simple peak-finding fitter.

    This is a simple class that finds the highest point in the data
    set.  It will not find secondary peaks.  It also requires a width
    parameter to give the size of the peak.  For example,

    >>> scan(TRANSLATION, start=-20, stop=20, step=1).Fit(PeakFit(5), uamps=1)

    Will use all of the points within 5 mm of the peak when fitting
    the quadratic.

    """

    def __init__(self, window=None):
        if window is None:
            raise RuntimeError(
                "PeakFit you to pass it requires a ± window size over which to"
                " fit the quadratic.  For example, PeakFit(5)")
        self._window = window
        self._fit = np.zeros(3)
        Fit.__init__(self, 3, "Peak")

    def _make_window(self, x, center):
        return np.abs(x-center) < self._window

    def fit(self, x, y):
        x = np.array(x)
        y = np.array(y)
        base = np.nanargmax(y)
        window = self._make_window(x, x[base])
        fit = np.polyfit(x[window], y[window], 2)
        self._fit = fit
        return np.array([-fit[1]/2/fit[0]])

    def get_y(self, x, fit):
        center = fit[0]
        y = x * 0
        if max(x) >= center >= min(x):
            window = self._make_window(x, center)
            y[window] = np.polyval(self._fit, x[window])
        return y

    def readable(self, fit):
        return {"peak": fit[0]}

    def title(self, center):
        # pylint: disable=arguments-differ
        return "Peak at {}".format(center)


@add_metaclass(ABCMeta)
class CurveFit(Fit):
    """
    A class for fitting models based on the scipy curve_fit optimizer
    """

    def __init__(self, degree, title):
        Fit.__init__(self, degree, title)

    @staticmethod
    @abstractmethod
    def _model(xs, *args):  # pragma: no cover
        """
        This is the mathematical model to be fit by the subclass
        """
        pass

    @staticmethod
    @abstractmethod
    def guess(x, y):
        """
        Given a set of x and y values, make a guess as to the initial
        parameters of the fit.
        """
        pass

    def fit(self, x, y):
        # raise maxfev to 10,000, this allows scipy to make more function calls,
        # improving the chances of getting a good/correct fit.
        return curve_fit(self._model, x, y, self.guess(x, y), maxfev=10000)[0]

    def get_y(self, x, fit):
        return self._model(x, *fit)


class GaussianFit(CurveFit):
    """
    A fitting class for handling gaussian peaks
    """

    def __init__(self):
        CurveFit.__init__(self, 4, "Gaussian Fit")
        import warnings
        warnings.simplefilter("ignore", OptimizeWarning)

    @staticmethod
    # pylint: disable=arguments-differ
    def _model(xs, cen, sigma, amplitude, background):
        """
        This is the model for a gaussian with the mean at center, a
        standard deviation of sigma, and a peak of amplitude over a base of
        background.

        """
        return background + amplitude * np.exp(-((xs - cen) / sigma /
                                                 np.sqrt(2)) ** 2)

    @staticmethod
    def guess(x, y):
        # Assume that amplitude is the difference between largest and smallest Y values.
        amplitude = np.max(y) - np.min(y)

        # guess that centre is the X value at which the highest Y value occurs.
        cen = x[np.argmax(y)]

        # Guess that the minimum Y value is representative of the background.
        background = np.min(y)

        # Predict a narrow peak somewhere within the scan. Estimating this much too large
        # can lead to an incorrect fit.
        sigma = (np.max(x) - np.min(x)) / 100

        return [cen, sigma, amplitude, background]

    def readable(self, fit):
        return {"center": fit[0], "sigma": fit[1],
                "amplitude": fit[2], "background": fit[3]}

    def title(self, params):
        # pylint: disable=arguments-differ
        params = self.readable(params)
        return (self._title + ": " +
                "y={amplitude:.3g}*exp((x-{center:.3g})$^2$" +
                "/{sigma:.3g})+{background:.1g}").format(**params)


class DampedOscillatorFit(CurveFit):
    """
    A class for fitting decaying cosine curves.
    """

    def __init__(self):
        CurveFit.__init__(self, 4, "Damped Oscillator")

    # pylint: disable=arguments-differ
    @staticmethod
    def _model(x, center, amp, freq, width):
        """
        This is the model for a damped Oscillator.

        Parameters
        ==========
        cen
          The center of the Damping
        amp
          The maximum amplitude
        freq
          The base frequency of the oscillator
        width
          The standard deviation of the damping.

        """
        return amp * np.cos((x-center)*freq)*np.exp(-((x-center)/width)**2)

    @staticmethod
    def guess(x, y):
        peak = x[np.argmax(y)]
        valley = x[np.argmin(y)]
        return [peak, 1, np.pi/np.abs(peak-valley), max(x)-min(x)]

    def readable(self, fit):
        return {"center": fit[0], "amplitude": fit[1],
                "frequency": fit[2], "width": fit[3]}

    def title(self, params):
        # pylint: disable=arguments-differ
        params = self.readable(params)
        return (self._title + ": " +
                "y={amplitude:.3g}*exp(-((x-{center:.3g})" +
                "/{width:.3g})$^2$)*" +
                "cos({frequency:.3g}*(x-{center:.3g}))").format(**params)


class ErfFit(CurveFit):
    """A simple Erf edge fitter.

    y = background + scale * erf(-stretch*(x-center))

    >>> scan(TRANSLATION, start=-20, stop=20, step=1).Fit(Erf, uamps=1)

    Will use all of the points within 5 mm of the peak when fitting
    the quadratic.

    """

    def __init__(self):
        CurveFit.__init__(self, 4, "Erf Fit")
        import warnings
        warnings.simplefilter("ignore", OptimizeWarning)

    @staticmethod
    # pylint: disable=arguments-differ
    def _model(xs, cen, stretch, scale, background):
        """
        This is the model for an error function centered at cen with
        an xscale of stretch and a yscale of scale over a base of
        background.
        """
        return background + scale * erf(stretch*(xs-cen))

    @staticmethod
    def guess(x, y):
        return [
            np.mean(x),  # center
            (max(x)-min(x))/2,  # stretch
            (max(y)-min(y))/2,  # scale
            min(y)]  # background

    def readable(self, fit):
        return {"center": fit[0], "stretch": fit[1],
                "scale": fit[2], "background": fit[3]}

    def title(self, fit):
        # pylint: disable=arguments-differ
        params = self.readable(fit)
        return "Edge at {center:.3g}".format(**params)


class TopHatFit(CurveFit):
    """A simple top hat finder.

    y = abs(x-center) < width/2 ? amplitude : background

    >>> scan(TRANSLATION, start=-20, stop=20, step=1).Fit(Erf, uamps=1)
    """

    def __init__(self):
        CurveFit.__init__(self, 5, "Top Hat Fit")
        import warnings
        warnings.simplefilter("ignore", OptimizeWarning)

    @staticmethod
    # pylint: disable=arguments-differ
    def _model(xs, cen, width, height, background):
        """
        This is the model for a top hat function centered at cen with
        a full width of width and a height of height over a base of
        background.
        """
        ys = xs * 0
        ys[np.abs(xs-cen) < width/2] = height
        return background + ys

    @staticmethod
    def guess(x, y):
        return [
            np.mean(x),  # center
            (max(x)-min(x))/2,  # stretch
            (max(y)-min(y))/2,  # scale
            min(y)]  # background

    def readable(self, fit):
        return {"center": fit[0], "width": fit[1],
                "height": fit[2], "background": fit[3]}

    def title(self, fit):
        # pylint: disable=arguments-differ
        params = self.readable(fit)
        return "Top Hat at {center:.3g} of width {width:.3g}".format(**params)


class CentreOfMassFit(Fit):
    """
    A fit that calculates the 'centre of mass' of a peak over a background.
    """
    def __init__(self):
        super(Fit, self).__init__()

    def fit(self, x, y):
        raw_data = np.array([(float(x_point), float(y_point)) for x_point, y_point in zip(x, y)])

        if len(raw_data) == 0:
            return [np.nan]

        # Sort data to ascending x (keeping the Y values with their associated X values).
        sorted_data = sorted(raw_data, key=lambda row: row[0])

        sorted_x = np.array([i[0] for i in sorted_data])
        sorted_y = np.array([i[1] for i in sorted_data])

        # Re-bin the points so that we have the same number of points,
        # but evenly spaced over the interval [min(data), max(data)]
        # Interpolate values in-between where necessary.
        interpolated_x = np.array(np.arange(np.min(x), np.max(x), float(np.max(x) - np.min(x))/len(raw_data)))
        interpolated_y = np.interp(interpolated_x, sorted_x, sorted_y)

        # Subtract background (assumed to be the minimum Y value)
        if len(interpolated_y) > 0:
            interpolated_y -= np.min(interpolated_y)

        # Calculate "centre of mass"
        centre_of_mass = np.sum(interpolated_x * interpolated_y) / np.sum(interpolated_y)
        return [centre_of_mass]

    def get_y(self, x, fit):
        return np.zeros(len(x))

    def title(self, params):
        return "Centre of mass = {}".format(params[0])

    def readable(self, fit):
        return {"Centre_of_mass": fit[0]}

    def fit_plot_action(self):
        def action(x, y, axis):
            """Fit and plot the data within the plotting loop

            Parameters
            ----------
            x : Array of Float
              The x positions measured thus far
            y : Array of Float
              The y positions measured thus far
            axis : matplotlib.axis.Axis
              The axis on which to plot

            Returns
            -------
            line : None or dict
                Either None if the fit is not possible or a dict of the fit
                parameters if the fit was performed

            """
            params = self.fit(x, y)
            axis.axvline(x=params[0])
            axis.legend([self.title(params)])
            return params
        return action


#: A linear regression
Linear = PolyFit(1, title="Linear")

#: A gaussian fit
Gaussian = GaussianFit()

DampedOscillator = DampedOscillatorFit()

Erf = ErfFit()

TopHat = TopHatFit()

ExactPoints = ExactFit()

CentreOfMass = CentreOfMassFit()

__all__ = ["PolyFit", "Linear", "Gaussian", "DampedOscillator", "PeakFit",
           "Erf", "TopHat", "ExactPoints", "CentreOfMass"]