# Ultralytics YOLO 🚀, GPL-3.0 license
import re

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from ultralytics.yolo.utils.torch_utils import get_flops, get_num_params

try:
    import clearml
    from clearml import Task

    assert hasattr(clearml, '__version__')
except (ImportError, AssertionError):
    clearml = None


def _log_debug_samples(files, title='Debug Samples'):
        """
        Log files (images) as debug samples in the ClearML task.

        arguments:
        files (List(PosixPath)) a list of file paths in PosixPath format
        title (str) A title that groups together images with the same values
        """
        for f in files:
            if f.exists():
                it = re.search(r'_batch(\d+)', f.name)
                iteration = int(it.groups()[0]) if it else 0
                Task.current_task().get_logger().report_image(title=title,
                                                              series=f.name.replace(it.group(), ''),
                                                              local_path=str(f),
                                                              iteration=iteration)

def _log_plot(title, plot_path):
        """
        Log image as plot in the plot section of ClearML

        arguments:
        title (str) Title of the plot
        plot_path (PosixPath or str) Path to the saved image file
        """
        img = mpimg.imread(plot_path)
        fig = plt.figure()
        ax = fig.add_axes([0, 0, 1, 1], frameon=False, aspect='auto', xticks=[], yticks=[])  # no ticks
        ax.imshow(img)

        Task.current_task().get_logger().report_matplotlib_figure(title, "", figure=fig, report_interactive=False)


def on_pretrain_routine_start(trainer):
    # TODO: reuse existing task
    task = Task.init(project_name=trainer.args.project or "YOLOv8",
                     task_name=trainer.args.name,
                     tags=['YOLOv8'],
                     output_uri=True,
                     reuse_last_task_id=False,
                     auto_connect_frameworks={'pytorch': False, 'matplotlib': False})
        # Make sure the code is easily remotely runnable by setting the docker image to use by the remote agent
    task.set_base_docker("ultralytics/ultralytics:latest",
                         docker_arguments='--ipc=host -e="CLEARML_AGENT_SKIP_PYTHON_ENV_INSTALL=1"',
                         docker_setup_bash_script='pip install clearml')
    task.connect(dict(trainer.args), name='General')


def on_train_epoch_end(trainer):
    if trainer.epoch == 1:
        _log_debug_samples(sorted(trainer.save_dir.glob('train_batch*.jpg')), "Mosaic")


def on_fit_epoch_end(trainer):
    # You should have access to the validation bboxes under jdict
    if trainer.epoch == 0:
        model_info = {
            "Parameters": get_num_params(trainer.model),
            "GFLOPs": round(get_flops(trainer.model), 3),
            "Inference speed (ms/img)": round(trainer.validator.speed[1], 3)}
        [Task.current_task().get_logger().report_single_value(k, v) for k, v in model_info.items()]

def on_val_end(validator):
    # Log val_labels and val_pred
    _log_debug_samples(sorted(validator.save_dir.glob('val*.jpg')), "Validation")

def on_train_end(trainer):
    # Log final results, CM matrix + PR plots
    files = ['results.png', 'confusion_matrix.png', *(f'{x}_curve.png' for x in ('F1', 'PR', 'P', 'R'))]
    files = [(trainer.save_dir / f) for f in files if (trainer.save_dir / f).exists()]  # filter
    [_log_plot(title=f.stem, plot_path=f) for f in files]
    # Report final metrics
    [Task.current_task().get_logger().report_single_value(k, v) for k, v in trainer.validator.metrics.results_dict.items()]

def on_model_save(trainer):
    if trainer.epoch % trainer.args.save_interval == 0:
        print("SAVING")
        # Upload the model checkpoints under the appropriate name
        Task.current_task().update_output_model(model_path=str(trainer.last),
                                                model_name=f"last_{trainer.args.name}",
                                                auto_delete_file=False)
        # Task.current_task().update_output_model(model_path=str(trainer.best),
        #                                         model_name=f"best_{trainer.args.name}",
        #                                         auto_delete_file=False)



callbacks = {
    "on_pretrain_routine_start": on_pretrain_routine_start,
    "on_model_save": on_model_save,
    "on_train_epoch_end": on_train_epoch_end,
    "on_fit_epoch_end": on_fit_epoch_end,
    "on_val_end": on_val_end,
    "on_train_end": on_train_end} if clearml else {}
