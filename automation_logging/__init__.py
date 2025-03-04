"""
Automation Logging
====
* **Thread-Safe Logging:** Ensures reliable and consistent logging from multi-threaded applications, preventing message corruption.
* **Automated Log Management:** Simplifies log file maintenance with configurable retention policies based on age or file count.
* **Seamless Integration:** Enables effortless integration with existing projects by allowing the library to override the standard `logging` module's root logger.
* **Integrated Screenshot Capture:** Captures informative screenshots directly within your logs, supporting full-screen captures (using `pyautogui`) and Selenium WebDriver screenshots, including headless browser support (using `selenium`).
"""

__version__ = "1.0.0"

from typing import Optional
import logging
import os
import shutil
import sys
import getpass
import traceback
import platform
import threading
from enum import IntEnum
from datetime import datetime, timedelta

try:
    from selenium.webdriver.chrome.webdriver import WebDriver

    SELENIUM_INSTALLED = True
except ImportError:
    SELENIUM_INSTALLED = False

try:
    from pyautogui import screenshot

    PYAUTOGUI_INSTALLED = True
except ImportError:
    PYAUTOGUI_INSTALLED = False


class LogLevel(IntEnum):
    DEBUG = 1
    INFO = 2
    STAT = 3
    WARNING = 4
    ERROR = 5
    EXCEPTION = 6
    CRITICAL = 7

    def to_logging_level(self):
        """Returns the corresponding logging level from the logging module."""
        if self == LogLevel.DEBUG:
            return logging.DEBUG
        elif self == LogLevel.INFO:
            return logging.INFO
        elif self == LogLevel.STAT:
            return logging.INFO + 5
        elif self == LogLevel.WARNING:
            return logging.WARNING
        elif self == LogLevel.ERROR:
            return logging.ERROR
        elif self == LogLevel.EXCEPTION:
            return logging.ERROR  # logging.exception also uses logging.ERROR level
        elif self == LogLevel.CRITICAL:
            return logging.CRITICAL
        else:
            raise ValueError(f"Unknown LogLevel: {self}")


class AutomationLogger:
    """
    from .automation_logging import *

        Class used to log the program execution to a file

        Examples
        --------
        >>> log_dir = "./tests/Logs"
        >>> log = AutomationLogger(script_path=__file__, log_dir=log_dir, log_to_console=True)
        >>>
        >>> log.info("Start of program")
        >>> for i in range(10):
        >>>     log.info(f"Iteration index: {i}")
        >>> try:
        >>>     error = 1 / 0
        >>> except Exception as exc:
        >>>     log.exception(f"Exception caught: {repr(exc)}")
        >>> log.info("End of program")
    """

    def __init__(
        self,
        script_path: str,
        log_dir: Optional[str] = None,
        log_to_console: bool = True,
        max_logs: int = 60,
        max_days: int = 30,
        encoding: str = "utf-8",
        as_logging_root: bool = False,
        as_global_log: bool = True,
        level_threshold: LogLevel = LogLevel.INFO,
    ) -> None:
        """
        Initializes a AutomationLogger object for standardized logging in a script or robot.

        This class introduces a log level called "STAT" (short for statistics), designed
        for dumping dictionaries of information usable with logging solutions (e.g., ELK stack).

        Parameters
        ----------
        script_path : str
            Absolute path of the script calling this function. Use __file__ or
            os.path.abspath(__file__) to retrieve the path.

        log_dir : str, optional
            Path to the directory where logs will be stored. If None, logs will be stored
            in the directory script_path/Logs.

        log_to_console : bool, optional
            If True, log messages will also appear on the console.

        max_logs : int, optional
            Number of log files to retain in the log directory.

        max_days : int, optional
            Number of days of log history to retain in the log folder.

        encoding : str, optional
            Encoding used by the logger object.

        as_logging_root: bool, optional
            Flag that controls if the root logger of the `logging` library will use the same configurations as AutomationLogger
            When set, code that uses `logging` functions (e.g info(), error()...) will follow the AutomationLogger configuration

            One reason to keep it as False is to avoid polluting the log with messages from packages that use `logging` internally

        as_global_log: bool, optional
            Flag that controls if this logger object will be set as the module's global logger.
            When set, it will be possible to use the module's logging functions without using set_global_log

        level_threshold: LogLevel
            Lowest log level that will be logged, any level less severe than the current one will be ignored.
            The order from least severe to most severe: debug, info, state, warning, error, exception, critical

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If `mode` passed is invalid
        ValueError
            If `max_logs` is not a positive integer
        ValueError
            If `max_days` is not a positive integer

        Examples
        --------
        >>> import logging
        >>> from automation_logging import AutomationLogger
        >>>
        >>> log_dir = "./tests/Logs"
        >>> logger = AutomationLogger(script_path=__file__, log_dir=log_dir, log_to_console=True, set_logging_root = True)
        >>> logger.info("This INFO message was written using a AutomationLogger method")
        >>> logging.info("This INFO message was written using a logging function and was written to the same file")
        """

        if not isinstance(max_logs, int) or max_logs <= 0:
            raise ValueError("max_logs parameter must be a positive integer")
        if not isinstance(max_days, int) or max_days <= 0:
            raise ValueError("max_days parameter must be a positive integer")
        if not isinstance(level_threshold, LogLevel):
            raise ValueError("level_threshold must be a LogLevel")

        log_dir = log_dir or os.path.join(os.path.dirname(script_path), "Logs")
        script_name = os.path.basename(script_path)
        script_name_no_ext = os.path.splitext(script_name)[0]
        log_name = f"{script_name_no_ext}.log"

        self.log_dir = None
        self.log_file = None
        self.threshold = level_threshold
        self._logger = None
        # Include private mutex to make this class thread-safe
        self._mutex = threading.Lock()

        try:

            # Delete older files and create current directory
            self.log_dir = self._clear_log_dir(
                log_dir=log_dir,
                max_logs=max_logs,
                max_days=max_days,
            )
            self.log_file = os.path.join(self.log_dir, log_name)

            # Getting system and user information to include in the log
            system_name = platform.node()
            user_domain = os.environ.get("USERDOMAIN", "-")
            if user_domain == "-":
                complete_user = getpass.getuser()
            else:
                complete_user = f"{user_domain}\\{getpass.getuser()}"
            # Configuring the logger object
            # include -10s to levelname to make all messages start at the same column
            _log_format = (
                f"%(asctime)s | {system_name} | {complete_user} | %(name)s"
                " | %(levelname)-10s | %(message)s"
            )

            self._logger = logging.getLogger(name=script_name)
            self._logger.setLevel(level_threshold.to_logging_level())

            self._logger.handlers = []  # Reset handlers

            # Formatter
            formatter = logging.Formatter(_log_format, datefmt="%Y-%m-%d %H:%M:%S%z")

            # log to file
            file_handler = logging.FileHandler(self.log_file, encoding=encoding)
            file_handler.setLevel(level_threshold.to_logging_level())
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

            # print in console
            if log_to_console:
                self._logger.addHandler(logging.StreamHandler(sys.stdout))

            # Create new log level
            add_logging_level("STAT", LogLevel.STAT.to_logging_level())

            if as_logging_root:
                logging.root = self._logger
                logging.getLogger().handlers = self._logger.handlers
                logging.getLogger().setLevel(self._logger.level)

            if as_global_log:
                set_global_log(self)

            self.info("AutomationLogger object instantiated")
        except Exception as exc:
            print(f"Error when instantiating AutomationLogger object: {repr(exc)}")
            error_traceback = traceback.format_exc()
            print(error_traceback)
            print("Writing the error inside log_error.txt")
            file_path = os.path.abspath("log_error.txt")
            with open(file_path, "w+", encoding="utf-8") as file:
                file.write(f"Error when instantiating AutomationLogger object: {repr(exc)}\n")
                file.write("----------------------------------------------------------\n")
                file.write(error_traceback)
            raise exc

    def _clear_log_dir(self, log_dir, max_logs, max_days) -> str:
        """
        Deletes old logs and creates the directory for the current log.

        Parameters
        ----------
        log_dir : str
            Path to the directory where logs will be stored. If None, logs will be stored
            in the directory specified during initialization.

        max_logs : int
            Number of log files to retain in the log directory.

        max_days : int
            Number of days of log history to retain in the log folder.

        Returns
        -------
        str
            String with the folder path for the current execution.
        """

        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("exec_%Y-%m-%d_%H-%M-%S")
        # Delete older execution if limit of executions has been reached
        # Condition 1) Delete based on the number of log files
        files = sorted(
            [
                x
                for x in os.listdir(log_dir)
                if os.path.isdir(os.path.join(log_dir, x)) and "exec_" in x.lower()
            ]
        )
        num_delete = max(len(files) - max_logs + 1, 0)
        for i in range(num_delete):
            try:
                shutil.rmtree(os.path.join(log_dir, files[i]))
            except PermissionError as exc:
                # In case of permission error when deleting files, instead of crashing the program,
                # the files won't be deleted (need to be manually deleted)
                print(f"Error when deleting old log files: {repr(exc)}")

        # Condition 2) Delete based on date in the file name and a cutoff date
        cutoff_date = datetime.now() - timedelta(days=max_days)
        files = [
            x
            for x in os.listdir(log_dir)
            if os.path.isdir(os.path.join(log_dir, x)) and "exec_" in x.lower()
        ]
        for file in files:
            try:
                file_date = datetime.strptime(file, "exec_%Y-%m-%d_%H-%M-%S")
                if file_date <= cutoff_date:
                    shutil.rmtree(os.path.join(log_dir, file))
            except Exception as exc:
                print(f"Error when deleting old log files: {repr(exc)}")

        log_dir = os.path.join(log_dir, timestamp)

        # Create log dir for the current execution
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    def _write(self, message: any, level: LogLevel) -> None:
        """Writes the message to the log file with the given level
        If the level is lower than the threshold, the message is not written

        Parameters
        ----------
        message: any
            Message to be logged

        Returns
        -------
        None
        """

        if level < self.threshold:
            return None

        with self._mutex:
            if level == LogLevel.DEBUG:
                self._logger.debug(message)
            elif level == LogLevel.INFO:
                self._logger.info(message)
            elif level == LogLevel.STAT:
                self._logger.stat(message)
            elif level == LogLevel.WARNING:
                self._logger.warning(message)
            elif level == LogLevel.ERROR:
                self._logger.error(message)
            elif level == LogLevel.EXCEPTION:
                self._logger.exception(message)
            elif level == LogLevel.CRITICAL:
                self._logger.critical(message)
            else:
                print(f"Unknown log level: {level}")

    def debug(self, message: any) -> None:
        """Writes the message to the log file with level DEBUG

        Parameters
        ----------
        message : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> log.debug(f"This is a DEBUG example")
        """

        self._write(message, LogLevel.DEBUG)

    def info(self, message: any) -> None:
        """
        Writes the message to the log file with level INFO.

        Parameters
        ----------
        message : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> log.info(f"This is an INFO example")
        """

        self._write(message, LogLevel.INFO)

    def warning(self, message: any) -> None:
        """
        Writes the message to the log file with level WARNING.

        Parameters
        ----------
        message : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> log.warning("This is a WARNING example")
        """

        self._write(message, LogLevel.WARNING)

    def error(self, message: any) -> None:
        """
        Writes the message to the log file with level ERROR.

        The difference between log.error and log.exception is that log.exception also prints
        the stack traceback of the exception.

        Parameters
        ----------
        message : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> try:
        >>>     a = 1/0
        >>> except Exception as exc:
        >>>     log.error(f"This is an ERROR example: {repr(exc)}")
        """

        self._write(message, LogLevel.ERROR)

    def critical(self, message: any) -> None:
        """
        Writes the message to the log file with level CRITICAL.

        Parameters
        ----------
        message : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> is_valid = check_critical_component(...)
        >>> if not is_valid:
        >>>     log.critical("This is a CRITICAL example, cannot continue")
        >>>     sys.exit(2)
        """

        self._write(message, LogLevel.CRITICAL)

    def exception(self, message: any) -> None:
        """
        Writes an exception to the log file with level ERROR.

        The difference between log.error and log.exception is that log.exception also prints
        the stack traceback of the exception.

        Parameters
        ----------
        message : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> try:
        >>>     a = 1/0
        >>> except Exception as exc:
        >>>     log.exception(f"This is an EXCEPTION example: {repr(exc)}")
        """

        self._write(message, LogLevel.EXCEPTION)

    def stat(self, info_dict: any) -> None:
        """
        Writes a dictionary to the log file with level STAT.

        This method should be used to aggregate or summarize information in a single message
        to facilitate the use of analytics solutions like elastic and opensearch.

        Parameters
        ----------
        info_dict : any
            Message to be logged

        Returns
        -------
        None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> info_dict = {"program_name": "Test Program", "var1": "StringVariable", "var2": 3}
        >>> log.stat(info_dict)
        """

        self._write(info_dict, LogLevel.STAT)

    def capture_screenshot(self, filename: Optional[str] = None) -> str:
        """
        Captures a screenshot of the entire screen and saves it in the log directory.

        The name of the screenshot is written with level INFO in the log file with the format:
        log_timestamp_screenshot.png or the filename parameter.

        Parameters
        ----------
        filename : str, optional
            Name of the screenshot. The file extension will be .png. If a file with the same
            name already exists, the new file will be named with a suffix (x), where x is
            the number of existing files with the same name. Example: image.png, image (1).png,
            image(2).png, image(3).png.

        Returns
        -------
        filename : str
            The name of the file saved

        Raises
        ------
        ValueError
            If the `filename` passed is not a string

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> log.capture_screenshot("example_screenshot.png")
        """

        if not PYAUTOGUI_INSTALLED:
            raise NotImplementedError("Function is only available if pyautogui is installed")

        if filename is not None and not isinstance(filename, str):
            raise ValueError("filename must be a string")

        timestamp = datetime.now().strftime(r"%Y_%m_%d-%H_%M_%S")
        if filename is None:
            basename = f"screenshot_{timestamp}"
        else:
            basename = os.path.splitext(filename)[0]
        filename = basename + ".png"

        with self._mutex:
            suffix = 0
            # If file with same name exists, include a suffix (number)
            while os.path.exists(os.path.join(self.log_dir, filename)):
                suffix += 1
                filename = f"{basename} ({suffix}).png"
            screenshot(os.path.join(self.log_dir, filename))
            self._logger.info(f"Screenshot captured and saved as: {filename}")

        return filename

    def capture_screenshot_selenium(self, driver: any, filename: Optional[str] = None) -> str:
        """
        Captures a screenshot of a Selenium driver instance.

        The name of the screenshot is written with level INFO in the log file with the format:
        log_timestamp_screenshot_selenium.png or the filename parameter.

        Parameters
        ----------
        driver : WebDriver
            Selenium WebDriver instance from which to capture the screenshot.

        filename : str, optional
            Name of the screenshot. If a file with the same name already exists, the new file
            will be named with a suffix (x), where x is the number of existing files with the
            same name. Example: image.png, image (1).png, image(2).png, image(3).png.

        Returns
        -------
        filename : str
            The name of the file saved

        Raises
        ------
        ValueError
            If the `filename` passed is not a string

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> driver = selenium.webdriver.Chrome(...)
        >>> log.capture_screenshot_selenium(driver, "chromedriver_screenshot.png")
        """

        if not SELENIUM_INSTALLED:
            raise NotImplementedError("Function is only available if selenium is installed")

        if filename is not None and not isinstance(filename, str):
            raise ValueError("filename must be a string")

        timestamp = datetime.now().strftime(r"%Y_%m_%d-%H_%M_%S")
        if filename is None:
            basename = f"selenium_screenshot_{timestamp}"
        else:
            basename = os.path.splitext(filename)[0]
        filename = basename + ".png"

        with self._mutex:
            # If file with same name exists, include a suffix (number)
            suffix = 0
            while os.path.exists(os.path.join(self.log_dir, filename)):
                suffix += 1
                filename = f"{basename} ({suffix}).png"

            driver.save_screenshot(os.path.join(self.log_dir, filename))
            self._logger.info(f"Selenium screenshot captured and saved as: {filename}")

        return filename

    def group_by_prefix(self, prefix: Optional[str] = None, sep: Optional[str] = None):
        """
        Group files in the log directory by prefix.
        If `prefix` is given all files that don't have the prefix will be ignored.
        If `sep` is given all files will be grouped according to automatic prefixes defined by the
        text before the separator.
        `prefix` takes priority over `sep` if both are set

        This function is useful to group images captured during the execution

        Parameters
        ----------
        prefix: str, optional
            Prefix of files that will be grouped inside the folder `prefix` in the log directory

        sep: str, optional
            Separator used to split file names and automatically determine file prefixes.
            Files with the same prefix will be grouped inside the same folder in the log directory

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the `prefix` and `sep` are None

        Examples
        --------
        >>> log = AutomationLogger(script_path=__file__)
        >>> # Manual prefix
        >>> log.capture_screenshot("ABC - Image 1")
        >>> log.capture_screenshot("ABC - Image 2")
        >>> log.capture_screenshot("ABC - Image 3")
        >>> log.group_by_prefix(prefix="ABC") # creates folder "ABC"
        >>> # Automatic Prefix
        >>> log.capture_screenshot("ABC - Image 1")
        >>> log.capture_screenshot("ABC - Image 2")
        >>> log.capture_screenshot("ABCD - Image 1")
        >>> log.group_by_prefix(sep="-") # creates folders "ABC" and "ABCD"
        """

        if prefix is None and sep is None:
            raise ValueError("prefix or sep must be set")

        with self._mutex:
            if prefix is not None:
                prefixes = [str(prefix)]
            else:
                sep = str(sep)
                files = [x for x in os.listdir(self._log_dir) if sep in x and x != self._log_name]
                prefixes = set(x.split(sep)[0] for x in files)

            for prefix in prefixes:
                prefix = prefix.strip()
                files = [
                    x
                    for x in os.listdir(self._log_dir)
                    if x.startswith(prefix) and x != self._log_name
                ]
                os.makedirs(os.path.join(self._log_dir, prefix), exist_ok=True)
                for file in files:
                    shutil.move(
                        os.path.join(self._log_dir, file),
                        os.path.join(self._log_dir, prefix),
                    )
                self.info(f"Grouped files by prefix: {prefix}")


def add_logging_level(levelName, levelNum, methodName=None):
    """
    Comprehensively adds a new logging level to the `logging` module and the
    currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    Parameters
    ----------
    levelName : str
        Name of the new logging level.

    levelNum : int
        Numeric value assigned to the new logging level.

    methodName : str, optional
        Name of the convenience method for the new logging level. If not specified,
        `levelName.lower()` is used.

    Returns
    -------
    None

    Examples
    --------
    >>> add_logging_level('TRACE', logging.DEBUG - 5)
    >>> logging.getLogger(__name__).setLevel("TRACE")
    >>> logging.getLogger(__name__).trace('that worked')
    >>> logging.trace('so did this')
    >>> logging.TRACE
    5

    Notes
    -----
    This method was extracted from:
    https://stackoverflow.com/q/2183233/35804945#35804945
    The behavior was modified to return None if the level is already defined
    instead of throwing an exception, allowing re-initialization of the log.
    """
    if not methodName:
        methodName = levelName.lower()

    if (
        hasattr(logging, levelName)
        or hasattr(logging, methodName)
        or hasattr(logging.getLoggerClass(), methodName)
    ):
        return None

    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)

    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


# -------------------------------------------------------------------------------------
# Global Logging (no need to pass AutomationLogger between functions)
# -------------------------------------------------------------------------------------

global_log: Optional[AutomationLogger] = None


def set_global_log(logger):
    """
    Set the global log object of the `automation_logging` module

    Parameters
    ----------
    logger: AutomationLogger.
        The instance of AutomationLogger that will be used globally

    Returns
    -------
    None

    Examples
    --------
    >>> log_dir = "./tests/Logs"
    >>> log = AutomationLogger(script_path=__file__, log_dir=log_dir, log_to_console=True)
    >>> set_global_log(log)
    >>> info("This was printed by the global log")

    Notes
    -----
    This function is thread-safe
    """

    global global_log

    global_log = logger


def debug(message: any) -> None:
    """Writes the message to the log file with level DEBUG

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> debug(f"This is a DEBUG example")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.debug(message)


def debug_else(message: any) -> None:
    """Calls debug if global_log is set, else calls print"""
    if global_log is not None:
        debug(message)
    else:
        print(f"{'DEBUG':<10} | {message}")


def info(message: any) -> None:
    """Writes the message to the log file with level INFO

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> info(f"This is an INFO example")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.info(message)


def info_else(message: any) -> None:
    """Calls info if global_log is set, else calls print"""
    if global_log is not None:
        info(message)
    else:
        print(f"{'INFO':<10} | {message}")


def stat(message: any) -> None:
    """Writes the message to the log file with level STAT

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> info_dict = {"program_name": "Test Program", "var1": "StringVariable", "var2": 3}
    >>> stat(info_dict)

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.stat(message)


def stat_else(message: any) -> None:
    """Calls stat if global_log is set, else calls print"""
    if global_log is not None:
        stat(message)
    else:
        print(f"{'STAT':<10} | {message}")


def warning(message: any) -> None:
    """Writes the message to the log file with level WARNING

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> warning(f"This is a WARNING example")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.warning(message)


def warning_else(message: any) -> None:
    """Calls warning if global_log is set, else calls print"""
    if global_log is not None:
        debug(message)
    else:
        print(f"{'WARNING':<10} | {message}")


def error(message: any) -> None:
    """Writes the message to the log file with level ERROR

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> error(f"This is an ERROR example")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.error(message)


def error_else(message: any) -> None:
    """Calls error if global_log is set, else calls print"""
    if global_log is not None:
        error(message)
    else:
        print(f"{'ERROR':<10} | {message}")


def exception(message: any) -> None:
    """Writes the message to the log file with level EXCEPTION

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> try:
    >>>     a = 1/0
    >>> except Exception as exc:
    >>>     exception(f"This is an EXCEPTION example: {repr(exc)}")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.exception(message)


def exception_else(message: any) -> None:
    """Calls exception if global_log is set, else calls print"""
    if global_log is not None:
        exception(message)
    else:
        print(f"{'EXCEPTION':<10} | {message}")


def critical(message: any) -> None:
    """Writes the message to the log file with level CRITICAL

    Parameters
    ----------
    message : any
        Message to be logged

    Returns
    -------
    None

    Examples
    --------
    >>> log = AutomationLogger(script_path=__file__)
    >>> set_global_log(log)
    >>> is_valid = check_critical_component(...)
    >>> if not is_valid:
    >>>     critical("This is a CRITICAL example, cannot continue")
    >>>     sys.exit(2)

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.critical(message)


def critical_else(message: any) -> None:
    """Calls critical if global_log is set, else calls print"""
    if global_log is not None:
        critical(message)
    else:
        print(f"{'CRITICAL':<10} | {message}")


def capture_screenshot(filename: Optional[str] = None):
    """
    Captures a screenshot of the entire screen and saves it in the log directory.

    The name of the screenshot is written with level INFO in the log file with the format:
    log_timestamp_screenshot.png or the filename parameter.

    Parameters
    ----------
    filename : str, optional
        Name of the screenshot. The file extension will be .png. If a file with the same
        name already exists, the new file will be named with a suffix (x), where x is
        the number of existing files with the same name. Example: image.png, image (1).png,
        image(2).png, image(3).png.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the `filename` passed is not a string

    Examples
    --------
    >>> log_dir = "./tests/Logs"
    >>> log = AutomationLogger(script_path=__file__, log_dir=log_dir, log_to_console=True)
    >>> set_global_log(log)
    >>> capture_screenshot("example_screenshot.png")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    return global_log.capture_screenshot(filename)


def capture_screenshot_selenium(driver: any, filename: Optional[str] = None) -> str:
    """
    Captures a screenshot of a Selenium driver instance.

    The name of the screenshot is written with level INFO in the log file with the format:
    log_timestamp_screenshot_selenium.png or the filename parameter.

    Parameters
    ----------
    driver : WebDriver
        Selenium WebDriver instance from which to capture the screenshot.

    filename : str, optional
        Name of the screenshot. If a file with the same name already exists, the new file
        will be named with a suffix (x), where x is the number of existing files with the
        same name. Example: image.png, image (1).png, image(2).png, image(3).png.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the `filename` passed is not a string

    Examples
    --------
    >>> log_dir = "./tests/Logs"
    >>> log = AutomationLogger(script_path=__file__, log_dir=log_dir, log_to_console=True)
    >>> set_global_log(log)
    >>> driver = selenium.webdriver.Chrome(...)
    >>> capture_screenshot_selenium(driver, "chromedriver_screenshot.png")

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    return global_log.capture_screenshot_selenium(driver, filename)


def group_by_prefix(prefix: Optional[str] = None, sep: Optional[str] = None) -> None:
    """
    Group files in the log directory by prefix.
    If `prefix` is given all files that don't have the prefix will be ignored.
    If `sep` is given all files will be grouped according to automatic prefixes defined by the
    text before the separator.
    `prefix` takes priority over `sep` if both are set

    This function is useful to group images captured during the execution

    Parameters
    ----------
    prefix: str, optional
        Prefix of files that will be grouped inside the folder `prefix` in the log directory

    sep: str, optional
        Separator used to split file names and automatically determine file prefixes.
        Files with the same prefix will be grouped inside the same folder in the log directory

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the `prefix` and `sep` are None

    Examples
    --------
    >>> log_dir = "./tests/Logs"
    >>> log = AutomationLogger(script_path=__file__, log_dir=log_dir, log_to_console=True)
    >>> set_global_log(log)
    >>> # Manual prefix
    >>> capture_screenshot("ABC - Image 1")
    >>> capture_screenshot("ABC - Image 2")
    >>> capture_screenshot("ABC - Image 3")
    >>> group_by_prefix(prefix="ABC") # creates folder "ABC"
    >>> # Automatic Prefix
    >>> capture_screenshot("ABC - Image 1")
    >>> capture_screenshot("ABC - Image 2")
    >>> capture_screenshot("ABCD - Image 1")
    >>> group_by_prefix(sep="-") # creates folders "ABC" and "ABCD"

    Notes
    -----
    This function is thread-safe
    """
    if global_log is None:
        raise ValueError("This function requires the global log to be set")
    global_log.group_by_prefix(prefix, sep)
