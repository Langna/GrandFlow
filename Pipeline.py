#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make pipeline
"""

# ---------
# Change Logs:
# 2018-05-31
#
# ---------

__author__ = 'Li Pidong'
__email__ = 'lipidong@126.com'
__version__ = '0.0.1'
__status__ = 'Dev'

import collections
import copy
import os

import grandflow
from grandflow.util import mkdir, sub_basename

sjm_template = """
job_begin
  name {name}
  memory {memory}
  sched_options -cwd -q {queue} -V -S /bin/bash -pe smp {thread}
  cmd_begin
    {cmd}
  cmd_end
job_end
"""


def get_config(*args, file_type='yaml'):
    """get config from config

    Args:
        args (str): config file
    Kwargs:
        file_type (str): file type which can be yaml or json

    Returns: dict

    """
    if file_type == 'yaml':
        import yaml
        config_dict = {}
        for config_file in args:
            f = open(config_file)
            config_dict.update(yaml.load(f))
    # config_dict['paras'] = {}
    config_dict['paras'].update(config_dict['database'])
    config_dict['paras'].update(config_dict['softwares'])

    # 如果子模块中没有paras模块的key, 则更新
    # 子模块的参数优先级更高
    for key in config_dict.keys():
        if key not in ['paras', 'database', 'softwares']:
            config_dict[key].update({
                k: v
                for k, v in config_dict['paras'].items()
                if v not in config_dict[key]
            })
    return config_dict


class Pipeline(object):
    """generate the pipeline"""

    def __init__(self, name=None, path=None, sjm_bin=None):
        """init

        Args:
            path (str):
              the pipeline path, default is current word directory

        """
        if path:
            self._path = os.path.expanduser(path)
            mkdir(self._path)
        else:
            self._path = os.getcwd()
        mkdir(os.path.join(self._path, 'log'))
        if name:
            self._name = name
        else:
            self._name = ''

        if not sjm_bin:
            self._sjm_bin = 'sjm'

        self.tasks = []
        self._sjm_output = None
        self._sjm_bin = sjm_bin

    def add_task(self, task, prev_task=None):
        """add task to the pipeline

        Args:
            task (Task): task name

        """
        if prev_task:
            task.set_prev_task(prev_task)

        task.abs_path = os.path.join(self._path, task.path)
        mkdir(task.abs_path)
        task.proj_name = self._name  # set task project name
        self.tasks.append(task)

    def sjm(self, output=None):
        """if output, write sjm cmd to output file, otherwise return the string of sjm

        Args:
            output (str): output file path

        Returns: sjm string

        """
        order_template = 'order {current} after {prev}'
        cmd_chunk = []
        order_chunk = []

        for task in self.tasks:
            cmd_chunk.append(task.sjm)
            if not task.prev_task:
                continue
            for sub_name in task.subnames:
                for prev_sub_name in task.prev_task.subnames:
                    order_chunk.append(
                        order_template.format(
                            current=sub_name, prev=prev_sub_name))
        cmd_chunk_str = '\n'.join(cmd_chunk)
        order_chunk_str = '\n'.join(order_chunk)

        if output:
            output = os.path.expanduser(output)
            with open(output, 'w') as f:
                f.write(cmd_chunk_str + '\n')
                f.write(order_chunk_str + '\n')
                f.write('log_dir log' + '\n')
            self._sjm_output = output
        else:
            return '\n'.join([cmd_chunk_str, order_chunk_str])

    def sjm_run(self):
        """run sjm

        Args:
            arg1 (TODO): TODO

        Returns: TODO

        """
        os.chdir(self._path)
        sjm_path = os.path.join(self._path, 'sjm')
        os.system('{sjm} -i {sjm_file}'.format(
            bashrc=os.path.join(
                os.path.dirname(grandflow.__file__), 'config', 'bashrc'),
            sjm=self._sjm_bin,
            sjm_file=self._sjm_output))

    def shell(self, output=None):
        """if output, write the shell command line to the output,
            otherwise return script string

        Args:
            output (str): output file path

        Returns: shell script string

        """
        cmd_chunk = []
        for task in self.tasks:
            cmd_chunk.append(task.shell)
        cmd_chunk_str = '\n'.join(cmd_chunk)
        if output:
            output = os.path.expanduser(output)
            with open(output, 'w') as f:
                f.write(cmd_chunk_str)
        else:
            return cmd_chunk_str


class Task(object):
    """define a task including command line, parameters and previous task"""

    def __init__(self,
                 name,
                 cmd,
                 cmd_paras={},
                 sjm_paras={},
                 path='',
                 output='',
                 prev_task=None,
                 **kargs):
        """init

        Args:
            name (str): task name
            cmd (str): cmd line which can include {template}
            cmd_paras (dict): cmd parameters
            prev_task (Task): the previous task which sjm need
            path (str): relative path of task, will make the path as  subdirectory of the project path
            output (str): the path of output
            sjm_paras (dict): sjm parameters
            **kargs (dict): can set parameters of cmd

        """
        self._name = name
        self._cmd = cmd
        self._cmd_paras = cmd_paras
        self._prev_task = prev_task
        self.path = path
        self._output = output
        self._kargs = kargs
        self._sjm_paras = sjm_paras

        self.proj_name = ''
        self._subname_list = []

        if self._cmd_paras:
            self._cmd_paras.update(self._kargs)

    @property
    def subnames(self):
        """get task's subnames which will be used in the sjm script
        Returns: list including subnames

        """
        return self._subname_list

    @property
    def output(self):
        """TODO: Docstring for output.

        Returns: TODO

        """
        if isinstance(self._output, list):
            return [os.path.join(self.path, xx) for xx in self._output]
        else:
            return os.path.join(self.path, self._output)

    @output.setter
    def output(self, value):
        """set the output path

        Args:
            value (str): output path

        """
        self._output = value

    def get_cmd_dict(self):
        """
        Returns: dict including every subname and corresponding command line

        """
        self._subname_list = []
        cmd_count = 0
        cmd_dict = collections.OrderedDict()
        # 输入的参数dict中有包含list的，按照多个命令并行计算
        for k, v in self._cmd_paras.items():
            if isinstance(v, list) and len(v) > 0:
                self.cmd_multi_paras_dict[k] = v
                if cmd_count != 0 and len(v) != cmd_count:
                    raise ValueError(
                        "The number of parameters must be equal or equal to 1")
                else:
                    cmd_count = len(v)

        if not self.cmd_multi_paras_dict:
            subname = '%s_%s' % (self.proj_name, self._name)
            self._subname_list = [subname]
            # pdb.set_trace()
            cmd_dict[subname] = self._cmd.format(**self._cmd_paras)
            return cmd_dict

        for ii in range(len(list(self.cmd_multi_paras_dict.values())[0])):
            subname = '{proj_name}_{name}_{ii:0>3d}'.format(
                proj_name=self.proj_name, name=self._name, ii=ii)
            self._subname_list.append(subname)
            para_dict = copy.deepcopy(self._cmd_paras)
            for key in self.cmd_multi_paras_dict.keys():
                para_dict[key] = self.cmd_multi_paras_dict[key][ii]
            cmd_dict[subname] = self._cmd.format(**para_dict)

        return cmd_dict

    @property
    def name(self):
        """
        Returns: task's name

        """
        return self._name

    @property
    def prev_task(self):
        """
        Returns: previous task

        """
        return self._prev_task

    def set_prev_task(self, task):
        """set previous task

        Args:
            task (Task): Task instance

        """
        self._prev_task = task

    @property
    def sjm(self):
        """generate template
        Returns: TODO

        """
        sjm_cmd_list = []

        self.cmd_multi_paras_dict = {}
        self.cmd_dict = self.get_cmd_dict()
        if not self._sjm_paras:
            raise ValueError('The sjm parameters not exists')

        for subname, cmd in self.cmd_dict.items():
            self._sjm_paras['name'] = subname
            self._sjm_paras['cmd'] = cmd
            sjm_cmd_list.append(sjm_template.format(**self._sjm_paras))
        return '\n'.join(sjm_cmd_list)

    @property
    def shell(self):
        """generate shell script
        Returns: TODO

        """
        self.cmd_multi_paras_dict = {}
        self.cmd_dict = self.get_cmd_dict()
        shell_cmd = []
        for subname, cmd in self.cmd_dict.items():
            shell_cmd.append('# %s' % subname)
            shell_cmd.append(cmd)
        return '\n'.join(shell_cmd)

    def __str__(self):
        """__str__
        Returns: name

        """
        return self._name


def aligner(name, proj_name, fq_list, config, ref_version):
    """create aligner task

    Args:
        name (str): alinger name such as ngmlr, last
        fq_list (list): the list of fastq file

    output bam format fastq's base name + aliger + ref version
    Returns: aligner_task, merge_bam_task

    """
    aligner_output = [
        os.path.join(name,
                     sub_basename(
                         xx, 'bam', mid='.%s.%s' % (name, ref_version)))
        for xx in fq_list
    ]

    config[name].update({
        'ref': config['paras'][ref_version],
        'fq': fq_list,
        'output': aligner_output
    })

    aligner_task = Task(
        name,
        config[name]['cmd'],
        cmd_paras=config[name],
        sjm_paras=config[name],
        path=name)

    # merge bam
    merge_bam_output = os.path.join(name, '%s.%s.merge.%s.%s.bam' %
                                    (proj_name, name, name, ref_version))
    config['merge_bam'].update({
        'input_list': ' '.join(aligner_output),
        'output': merge_bam_output
    })
    merge_bam_task = Task(
        'merge_bam',
        config['merge_bam']['cmd'],
        cmd_paras=config['merge_bam'],
        sjm_paras=config['merge_bam'],
        output=merge_bam_output)
    # merge_bam.output = 'merge.bam'

    return aligner_task, merge_bam_task


def sv_caller(name, proj_name, input_bam, config):
    """ sv_caller.

    Args:
        name (TODO): the name of sv caller
        proj_name (str): project name
        input_bam (str): input bam
        config (dict): config

    Returns: sv caller task

    """
    if isinstance(input_bam, list):
        sv_caller_output = [
            os.path.join(name, '%s.%s.vcf' % (proj_name, name))
            for xx in input_bam
        ]
    else:
        sv_caller_output = os.path.join(name, '%s.%s.vcf' % (proj_name, name))

    config[name].update({'bam': input_bam, 'output': sv_caller_output})
    sv_caller_task = Task(
        name,
        config[name]['cmd'],
        cmd_paras=config[name],
        sjm_paras=config[name],
        path=name,
        output=sv_caller_output)
    return sv_caller_task


def fastq_stat(name, proj_name, fq_list_file, config):
    """TODO: Docstring for fastq_stat.

    Args:
        arg1 (TODO): TODO

    Returns: TODO

    """
    config[name].update({
        'fq_list_file': fq_list_file,
        'proj_name': proj_name,
        'out_dir': 'stat'
    })

    fastq_stat_task = Task(
        name,
        config[name]['cmd'],
        cmd_paras=config[name],
        sjm_paras=config[name],
        path='stat')
    return fastq_stat_task


def bam_stat(name, proj_name, input_bam, config):
    """stat bam and generate the plot

    Args:
        name (str): 'bam_stat'
        proj_name (TODO): project name
        bam_list (TODO): bam

    Returns: TODO

    """
    if isinstance(input_bam, list):
        input_bam = ' '.join(input_bam)

    config[name].update({
        'input_bam': input_bam,
        'proj_name': proj_name,
        'out_dir': 'stat'
    })

    bam_stat_task = Task(
        'bam_stat',
        config[name]['cmd'],
        cmd_paras=config[name],
        sjm_paras=config[name],
        path='stat')
    return bam_stat_task


def main():
    print('Pipeline Moudle')


if __name__ == '__main__':
    main()
