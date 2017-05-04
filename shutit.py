#!/usr/bin/env python
# The MIT License (MIT)
#
# Copyright (C) 2014 OpenBet Limited
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# ITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.



"""ShutIt is a means of building stateless target hosts in a flexible and predictable way.
"""
from __future__ import print_function
from distutils import spawn
import logging
import os
import re
import signal
import sys
import urllib
import shutit_global
import shutit_skeleton
import shutit_util
from shutit_module import ShutItModule


# run_order of -1 means 'stop everything'
def stop_all(shutit, run_order=-1):
	"""Runs stop method on all modules less than the passed-in run_order.
	Used when target is exporting itself mid-build, so we clean up state
	before committing run files etc.
	"""
	# sort them so they're stopped in reverse order
	for module_id in shutit_util.module_ids(shutit, rev=True):
		shutit_module_obj = shutit.shutit_map[module_id]
		if run_order == -1 or shutit_module_obj.run_order <= run_order:
			if shutit_util.is_installed(shutit, shutit_module_obj):
				if not shutit_module_obj.stop(shutit):
					shutit.fail('failed to stop: ' + module_id, shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').shutit_pexpect_child) # pragma: no cover


# Start all apps less than the supplied run_order
def start_all(shutit, run_order=-1):
	"""Runs start method on all modules less than the passed-in run_order.
	Used when target is exporting itself mid-build, so we can export a clean
	target and still depended-on modules running if necessary.
	"""
	# sort them so they're started in order
	for module_id in shutit_util.module_ids(shutit):
		shutit_module_obj = shutit.shutit_map[module_id]
		if run_order == -1 or shutit_module_obj.run_order <= run_order:
			if shutit_util.is_installed(shutit, shutit_module_obj):
				if not shutit_module_obj.start(shutit):
					shutit.fail('failed to start: ' + module_id, shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').shutit_pexpect_child) # pragma: no cover


def is_ready(shutit, shutit_module_obj):
	"""Returns true if this module is ready to be built.
	Caches the result (as it's assumed not to change during the build).
	"""
	if shutit_module_obj.module_id in shutit.get_current_shutit_pexpect_session_environment().modules_ready:
		shutit.log('is_ready: returning True from cache',level=logging.DEBUG)
		return True
	ready = shutit_module_obj.check_ready(shutit)
	if ready:
		shutit.get_current_shutit_pexpect_session_environment().modules_ready.append(shutit_module_obj.module_id)
		return True
	else:
		return False




def init_shutit_map(shutit):
	"""Initializes the module map of shutit based on the modules
	we have gathered.

	Checks we have core modules
	Checks for duplicate module details.
	Sets up common config.
	Sets up map of modules.
	"""
	modules = shutit.shutit_modules
	# Have we got anything to process outside of special modules?
	if len([mod for mod in modules if mod.run_order > 0]) < 1:
		shutit.log(modules,level=logging.DEBUG)
		path = ':'.join(shutit.host['shutit_module_path'])
		shutit.log('\nIf you are new to ShutIt, see:\n\n\thttp://ianmiell.github.io/shutit/\n\nor try running\n\n\tshutit skeleton\n\n',level=logging.INFO)
		if path == '':
			shutit.fail('No ShutIt modules aside from core ones found and no ShutIt module path given.\nDid you set --shutit_module_path/-m wrongly?\n') # pragma: no cover
		elif path == '.':
			shutit.fail('No modules aside from core ones found and no ShutIt module path given apart from default (.).\n\n- Did you set --shutit_module_path/-m?\n- Is there a STOP* file in your . dir?') # pragma: no cover
		else:
			shutit.fail('No modules aside from core ones found and no ShutIt modules in path:\n\n' + path + '\n\nor their subfolders. Check your --shutit_module_path/-m setting and check that there are ShutIt modules below without STOP* files in any relevant directories.') # pragma: no cover

	shutit.log('PHASE: base setup', level=logging.DEBUG)

	run_orders = {}
	has_core_module = False
	for module in modules:
		assert isinstance(module, ShutItModule)
		if module.module_id in shutit.shutit_map:
			shutit.fail('Duplicated module id: ' + module.module_id + '\n\nYou may want to check your --shutit_module_path setting') # pragma: no cover
		if module.run_order in run_orders:
			shutit.fail('Duplicate run order: ' + str(module.run_order) + ' for ' + module.module_id + ' and ' + run_orders[module.run_order].module_id + '\n\nYou may want to check your --shutit_module_path setting') # pragma: no cover
		if module.run_order == 0:
			has_core_module = True
		shutit.shutit_map[module.module_id] = run_orders[module.run_order] = module

	if not has_core_module:
		shutit.fail('No module with run_order=0 specified! This is required.') # pragma: no cover


def conn_target(shutit):
	"""Connect to the target.
	"""
	conn_module = None
	for mod in shutit.conn_modules:
		if mod.module_id == shutit.build['conn_module']:
			conn_module = mod
			break
	if conn_module is None:
		shutit.fail('Couldn\'t find conn_module ' + shutit.build['conn_module']) # pragma: no cover

	# Set up the target in pexpect.
	conn_module.get_config(shutit)
	conn_module.build(shutit)


def finalize_target(shutit):
	"""Finalize the target using the core finalize method.
	"""
	shutit.pause_point('\nFinalizing the target module (' + shutit.shutit_main_dir + '/shutit_setup.py)', print_input=False, level=3)
	# Can assume conn_module exists at this point
	for mod in shutit.conn_modules:
		if mod.module_id == shutit.build['conn_module']:
			conn_module = mod
			break
	conn_module.finalize(shutit)


# Once we have all the modules, then we can look at dependencies.
# Dependency validation begins.
def resolve_dependencies(shutit, to_build, depender):
	"""Add any required dependencies.
	"""
	shutit.log('In resolve_dependencies',level=logging.DEBUG)
	cfg = shutit.cfg
	for dependee_id in depender.depends_on:
		dependee = shutit.shutit_map.get(dependee_id)
		# Don't care if module doesn't exist, we check this later
		if (dependee and dependee not in to_build
		    and cfg[dependee_id]['shutit.core.module.build_ifneeded']):
			to_build.append(dependee)
			cfg[dependee_id]['shutit.core.module.build'] = True
	return True


def check_dependee_exists(shutit, depender, dependee, dependee_id):
	"""Checks whether a depended-on module is available.
	"""
	# If the module id isn't there, there's a problem.
	if dependee is None:
		return 'module: \n\n' + dependee_id + '\n\nnot found in paths: ' + str(shutit.host['shutit_module_path']) + ' but needed for ' + depender.module_id + '\nCheck your --shutit_module_path setting and ensure that all modules configured to be built are in that path setting, eg "--shutit_module_path /path/to/other/module/:."\n\nAlso check that the module is configured to be built with the correct module id in that module\'s configs/build.cnf file.\n\nSee also help.'


def check_dependee_build(shutit, depender, dependee, dependee_id):
	"""Checks whether a depended on module is configured to be built.
	"""
	cfg = shutit.cfg
	# If depender is installed or will be installed, so must the dependee
	if not (cfg[dependee.module_id]['shutit.core.module.build'] or
	        shutit_util.is_to_be_built_or_is_installed(shutit, dependee)):
		return 'depender module id:\n\n[' + depender.module_id + ']\n\nis configured: "build:yes" or is already built but dependee module_id:\n\n[' + dependee_id + ']\n\n is not configured: "build:yes"'


def check_dependee_order(shutit, depender, dependee, dependee_id):
	"""Checks whether run orders are in the appropriate order.
	"""
	# If it depends on a module id, then the module id should be higher up
	# in the run order.
	if dependee.run_order > depender.run_order:
		return 'depender module id:\n\n' + depender.module_id + '\n\n(run order: ' + str(depender.run_order) + ') ' + 'depends on dependee module_id:\n\n' + dependee_id + '\n\n(run order: ' + str(dependee.run_order) + ') ' + 'but the latter is configured to run after the former'


def make_dep_graph(depender):
	"""Returns a digraph string fragment based on the passed-in module
	"""
	digraph = ''
	for dependee_id in depender.depends_on:
		digraph = (digraph + '"' + depender.module_id + '"->"' + dependee_id + '";\n')
	return digraph


def check_deps(shutit):
	"""Dependency checking phase is performed in this method.
	"""
	cfg = shutit.cfg
	shutit.log('PHASE: dependencies', level=logging.DEBUG)
	shutit.pause_point('\nNow checking for dependencies between modules', print_input=False, level=3)
	# Get modules we're going to build
	to_build = [
		shutit.shutit_map[module_id] for module_id in shutit.shutit_map
		if module_id in cfg and cfg[module_id]['shutit.core.module.build']
	]
	# Add any deps we may need by extending to_build and altering cfg
	for module in to_build:
		resolve_dependencies(shutit, to_build, module)

	# Dep checking
	def err_checker(errs, triples):
		"""Collate error information.
		"""
		new_triples = []
		for err, triple in zip(errs, triples):
			if not err:
				new_triples.append(triple)
				continue
			found_errs.append(err)
		return new_triples

	found_errs = []
	triples    = []
	for depender in to_build:
		for dependee_id in depender.depends_on:
			triples.append((depender, shutit.shutit_map.get(dependee_id), dependee_id))

	triples = err_checker([ check_dependee_exists(shutit, depender, dependee, dependee_id) for depender, dependee, dependee_id in triples ], triples)
	triples = err_checker([ check_dependee_build(shutit, depender, dependee, dependee_id) for depender, dependee, dependee_id in triples ], triples)
	triples = err_checker([ check_dependee_order(shutit, depender, dependee, dependee_id) for depender, dependee, dependee_id in triples ], triples)

	if found_errs:
		return [(err,) for err in found_errs]

	shutit.log('Modules configured to be built (in order) are: ', level=logging.DEBUG)
	for module_id in shutit_util.module_ids(shutit):
		module = shutit.shutit_map[module_id]
		if cfg[module_id]['shutit.core.module.build']:
			shutit.log(module_id + '    ' + str(module.run_order), level=logging.DEBUG)
	shutit.log('\n', level=logging.DEBUG)

	return []


def check_conflicts(shutit):
	"""Checks for any conflicts between modules configured to be built.
	"""
	cfg = shutit.cfg
	# Now consider conflicts
	shutit.log('PHASE: conflicts', level=logging.DEBUG)
	errs = []
	shutit.pause_point('\nNow checking for conflicts between modules', print_input=False, level=3)
	for module_id in shutit_util.module_ids(shutit):
		if not cfg[module_id]['shutit.core.module.build']:
			continue
		conflicter = shutit.shutit_map[module_id]
		for conflictee in conflicter.conflicts_with:
			# If the module id isn't there, there's no problem.
			conflictee_obj = shutit.shutit_map.get(conflictee)
			if conflictee_obj is None:
				continue
			if ((cfg[conflicter.module_id]['shutit.core.module.build'] or
			     shutit_util.is_to_be_built_or_is_installed(shutit, conflicter)) and
			    (cfg[conflictee_obj.module_id]['shutit.core.module.build'] or
			     shutit_util.is_to_be_built_or_is_installed(shutit, conflictee_obj))):
				errs.append(('conflicter module id: ' + conflicter.module_id + ' is configured to be built or is already built but conflicts with module_id: ' + conflictee_obj.module_id,))
	return errs


def check_ready(shutit, throw_error=True):
	"""Check that all modules are ready to be built, calling check_ready on
	each of those configured to be built and not already installed
	(see shutit_util.is_installed).
	"""
	cfg = shutit.cfg
	shutit.log('PHASE: check_ready', level=logging.DEBUG)
	errs = []
	shutit.pause_point('\nNow checking whether we are ready to build modules configured to be built', print_input=False, level=3)
	# Find out who we are to see whether we need to log in and out or not.
	for module_id in shutit_util.module_ids(shutit):
		module = shutit.shutit_map[module_id]
		shutit.log('considering check_ready (is it ready to be built?): ' + module_id, level=logging.DEBUG)
		if cfg[module_id]['shutit.core.module.build'] and module.module_id not in shutit.get_current_shutit_pexpect_session_environment().modules_ready and not shutit_util.is_installed(shutit, module):
			shutit.log('checking whether module is ready to build: ' + module_id, level=logging.DEBUG)
			shutit.login(prompt_prefix=module_id,command='bash --noprofile --norc',echo=False)
			# Move to the correct directory (eg for checking for the existence of files needed for build)
			revert_dir = os.getcwd()
			shutit.get_current_shutit_pexpect_session_environment().module_root_dir = os.path.dirname(module.__module_file)
			shutit.chdir(shutit.get_current_shutit_pexpect_session_environment().module_root_dir)
			if not is_ready(shutit, module) and throw_error:
				errs.append((module_id + ' not ready to install.\nRead the check_ready function in the module,\nor log messages above to determine the issue.\n\n', shutit.get_shutit_pexpect_session_from_id('target_child')))
			shutit.logout(echo=False)
			shutit.chdir(revert_dir)
	return errs


def do_remove(shutit, loglevel=logging.DEBUG):
	"""Remove modules by calling remove method on those configured for removal.
	"""
	cfg = shutit.cfg
	# Now get the run_order keys in order and go.
	shutit.log('PHASE: remove', level=loglevel)
	shutit.pause_point('\nNow removing any modules that need removing', print_input=False, level=3)
	# Login at least once to get the exports.
	for module_id in shutit_util.module_ids(shutit):
		module = shutit.shutit_map[module_id]
		shutit.log('considering whether to remove: ' + module_id, level=logging.DEBUG)
		if cfg[module_id]['shutit.core.module.remove']:
			shutit.log('removing: ' + module_id, level=logging.DEBUG)
			shutit.login(prompt_prefix=module_id,command='bash --noprofile --norc',echo=False)
			if not module.remove(shutit):
				shutit.log(shutit_util.print_modules(shutit), level=logging.DEBUG)
				shutit.fail(module_id + ' failed on remove', shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').pexpect_child) # pragma: no cover
			else:
				if shutit.build['delivery'] in ('docker','dockerfile'):
					# Create a directory and files to indicate this has been removed.
					shutit.send(' command mkdir -p ' + shutit.build['build_db_dir'] + '/module_record/' + module.module_id + ' && command rm -f ' + shutit.build['build_db_dir'] + '/module_record/' + module.module_id + '/built && command touch ' + shutit.build['build_db_dir'] + '/module_record/' + module.module_id + '/removed', loglevel=loglevel)
					# Remove from "installed" cache
					if module.module_id in shutit.get_current_shutit_pexpect_session_environment().modules_installed:
						shutit.get_current_shutit_pexpect_session_environment().modules_installed.remove(module.module_id)
					# Add to "not installed" cache
					shutit.get_current_shutit_pexpect_session_environment().modules_not_installed.append(module.module_id)
			shutit.logout(echo=False)



def build_module(shutit, module, loglevel=logging.DEBUG):
	"""Build passed-in module.
	"""
	cfg = shutit.cfg
	shutit.log('Building ShutIt module: ' + module.module_id + ' with run order: ' + str(module.run_order), level=logging.INFO)
	shutit.build['report'] = (shutit.build['report'] + '\nBuilding ShutIt module: ' + module.module_id + ' with run order: ' + str(module.run_order))
	if not module.build(shutit):
		shutit.fail(module.module_id + ' failed on build', shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').pexpect_child) # pragma: no cover
	else:
		if shutit.build['delivery'] in ('docker','dockerfile'):
			# Create a directory and files to indicate this has been built.
			shutit.send(' command mkdir -p ' + shutit.build['build_db_dir'] + '/module_record/' + module.module_id + ' && command touch ' + shutit.build['build_db_dir'] + '/module_record/' + module.module_id + '/built && command rm -f ' + shutit.build['build_db_dir'] + '/module_record/' + module.module_id + '/removed', loglevel=loglevel)
		# Put it into "installed" cache
		shutit.get_current_shutit_pexpect_session_environment().modules_installed.append(module.module_id)
		# Remove from "not installed" cache
		if module.module_id in shutit.get_current_shutit_pexpect_session_environment().modules_not_installed:
			shutit.get_current_shutit_pexpect_session_environment().modules_not_installed.remove(module.module_id)
	shutit.pause_point('\nPausing to allow inspect of build for: ' + module.module_id, print_input=True, level=2)
	shutit.build['report'] = (shutit.build['report'] + '\nCompleted module: ' + module.module_id)
	if cfg[module.module_id]['shutit.core.module.tag']:
		shutit.log(shutit_util.build_report(shutit, '#Module:' + module.module_id), level=logging.DEBUG)
	if not cfg[module.module_id]['shutit.core.module.tag'] and shutit.build['interactive'] >= 2:
		print ("\n\nDo you want to save state now we\'re at the " + "end of this module? (" + module.module_id + ") (input y/n)")
		cfg[module.module_id]['shutit.core.module.tag'] = (shutit_util.util_raw_input(shutit, default='y') == 'y')
	if cfg[module.module_id]['shutit.core.module.tag'] or shutit.build['tag_modules']:
		shutit.log(module.module_id + ' configured to be tagged, doing repository work',level=logging.INFO)
		# Stop all before we tag to avoid file changing errors, and clean up pid files etc..
		stop_all(shutit, module.run_order)
		shutit.do_repository_work(str(module.module_id) + '_' + str(module.run_order), password=shutit.host['password'], docker_executable=shutit.host['docker_executable'], force=True)
		# Start all after we tag to ensure services are up as expected.
		start_all(shutit, module.run_order)
	if shutit.build['interactive'] >= 2:
		print ("\n\nDo you want to stop interactive mode? (input y/n)\n")
		if shutit_util.util_raw_input(shutit, default='y') == 'y':
			shutit.build['interactive'] = 0


def do_build(shutit):
	"""Runs build phase, building any modules that we've determined
	need building.
	"""
	cfg = shutit.cfg
	shutit.log('PHASE: build, repository work', level=logging.DEBUG)
	module_id_list = shutit_util.module_ids(shutit)
	if shutit.build['deps_only']:
		module_id_list_build_only = filter(lambda x: cfg[x]['shutit.core.module.build'], module_id_list)
	for module_id in module_id_list:
		module = shutit.shutit_map[module_id]
		shutit.log('Considering whether to build: ' + module.module_id, level=logging.INFO)
		if cfg[module.module_id]['shutit.core.module.build']:
			if shutit.build['delivery'] not in module.ok_delivery_methods:
				shutit.fail('Module: ' + module.module_id + ' can only be built with one of these --delivery methods: ' + str(module.ok_delivery_methods) + '\nSee shutit build -h for more info, or try adding: --delivery <method> to your shutit invocation') # pragma: no cover
			if shutit_util.is_installed(shutit, module):
				shutit.build['report'] = (shutit.build['report'] + '\nBuilt already: ' + module.module_id + ' with run order: ' + str(module.run_order))
			else:
				# We move to the module directory to perform the build, returning immediately afterwards.
				if shutit.build['deps_only'] and module_id == module_id_list_build_only[-1]:
					# If this is the last module, and we are only building deps, stop here.
					shutit.build['report'] = (shutit.build['report'] + '\nSkipping: ' + module.module_id + ' with run order: ' + str(module.run_order) + '\n\tas this is the final module and we are building dependencies only')
				else:
					revert_dir = os.getcwd()
					shutit.get_current_shutit_pexpect_session_environment().module_root_dir = os.path.dirname(module.__module_file)
					shutit.chdir(shutit.get_current_shutit_pexpect_session_environment().module_root_dir)
					shutit.login(prompt_prefix=module_id,command='bash --noprofile --norc',echo=False)
					build_module(shutit, module)
					shutit.logout(echo=False)
					shutit.chdir(revert_dir)
		if shutit_util.is_installed(shutit, module):
			shutit.log('Starting module',level=logging.DEBUG)
			if not module.start(shutit):
				shutit.fail(module.module_id + ' failed on start', shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').pexpect_child) # pragma: no cover


def do_test(shutit):
	"""Runs test phase, erroring if any return false.
	"""
	if not shutit.build['dotest']:
		shutit.log('Tests configured off, not running',level=logging.DEBUG)
		return
	# Test in reverse order
	shutit.log('PHASE: test', level=logging.DEBUG)
	stop_all(shutit)
	start_all(shutit)
	for module_id in shutit_util.module_ids(shutit, rev=True):
		# Only test if it's installed.
		if shutit_util.is_installed(shutit, shutit.shutit_map[module_id]):
			shutit.log('RUNNING TEST ON: ' + module_id, level=logging.DEBUG)
			shutit.login(prompt_prefix=module_id,command='bash --noprofile --norc',echo=False)
			if not shutit.shutit_map[module_id].test(shutit):
				shutit.fail(module_id + ' failed on test', shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').pexpect_child) # pragma: no cover
			shutit.logout(echo=False)


def do_finalize(shutit=None):
	"""Runs finalize phase; run after all builds are complete and all modules
	have been stopped.
	"""
	def _finalize(shutit):
		# Stop all the modules
		stop_all(shutit)
		# Finalize in reverse order
		shutit.log('PHASE: finalizing object ' + str(shutit), level=logging.DEBUG)
		# Login at least once to get the exports.
		for module_id in shutit_util.module_ids(shutit, rev=True):
			# Only finalize if it's thought to be installed.
			if shutit_util.is_installed(shutit, shutit.shutit_map[module_id]):
				shutit.login(prompt_prefix=module_id,command='bash --noprofile --norc',echo=False)
				if not shutit.shutit_map[module_id].finalize(shutit):
					shutit.fail(module_id + ' failed on finalize', shutit_pexpect_child=shutit.get_shutit_pexpect_session_from_id('target_child').pexpect_child) # pragma: no cover
				shutit.logout(echo=False)
	if shutit is None:
		for shutit in shutit_global.shutit_global_object.shutit_objects:
			_finalize(shutit)
	else:
		_finalize(shutit)


def setup_shutit_path(shutit):
	# try the current directory, the .. directory, or the ../shutit directory, the ~/shutit
	if not shutit.host['add_shutit_to_path']:
		return
	res = shutit_util.util_raw_input(shutit, prompt='shutit appears not to be on your path - should try and we find it and add it to your ~/.bashrc (Y/n)?')
	if res in ['n','N']:
		with open(os.path.join(shutit.host['shutit_path'], 'config'), 'a') as f:
			f.write('\n[host]\nadd_shutit_to_path: no\n')
		return
	path_to_shutit = ''
	for d in ['.','..','~','~/shutit']:
		path = os.path.abspath(d + '/shutit')
		if not os.path.isfile(path):
			continue
		path_to_shutit = path
	while path_to_shutit == '':
		d = shutit_util.util_raw_input(shutit, prompt='cannot auto-find shutit - please input the path to your shutit dir\n')
		path = os.path.abspath(d + '/shutit')
		if not os.path.isfile(path):
			continue
		path_to_shutit = path
	if path_to_shutit != '':
		bashrc = os.path.expanduser('~/.bashrc')
		with open(bashrc, "a") as myfile:
			#http://unix.stackexchange.com/questions/26676/how-to-check-if-a-shell-is-login-interactive-batch
			myfile.write('\nexport PATH="$PATH:' + os.path.dirname(path_to_shutit) + '"\n')
		shutit_util.util_raw_input(shutit, prompt='\nPath set up - please open new terminal and re-run command\n')
		shutit_util.handle_exit(shutit=shutit)



def main():
	"""Main ShutIt function.

	Handles the configured actions:

		- skeleton     - create skeleton module
		- list_configs - output computed configuration
		- depgraph     - output digraph of module dependencies
	"""
	shutit = shutit_global.shutit_global_object.shutit_objects[0]
	if sys.version_info.major == 2:
		if sys.version_info.minor < 7:
			shutit.fail('Python version must be 2.7+') # pragma: no cover
	setup_shutit_obj(shutit)


def setup_shutit_obj(shutit):

	shutit_util.parse_args(shutit)
	if not shutit.build['exam']:
		shutit.log('# ShutIt Started... ',transient=True)
		shutit.log('# Loading configs...',transient=True)
	shutit_util.load_configs(shutit)

	if shutit.action['skeleton']:
		shutit_skeleton.create_skeleton(shutit)
		shutit.build['completed'] = True
		return

	# Try and ensure shutit is on the path - makes onboarding easier
	# Only do this if we're in a terminal
	if shutit_util.determine_interactive(shutit) and spawn.find_executable('shutit') is None:
		setup_shutit_path(shutit)

	shutit_util.load_mod_from_file(shutit, os.path.join(shutit.shutit_main_dir, 'shutit_setup.py'))
	shutit_util.load_shutit_modules(shutit)
	shutit.log('ShutIt modules loaded',level=logging.INFO)

	init_shutit_map(shutit)

	shutit_util.config_collection(shutit=shutit)
	shutit.log('Configuration loaded',level=logging.INFO)

	if shutit.action['list_modules']:
		shutit_util.list_modules(shutit)
		shutit_util.handle_exit(shutit=shutit)
	if not shutit.action['list_deps'] and not shutit.action['list_modules']:
		conn_target(shutit)
		shutit.log('Connected to target',level=logging.INFO)

	if shutit.build['interactive'] > 0 and shutit.build['choose_config']:
		errs = do_interactive_modules(shutit)
	else:
		errs = []
		errs.extend(check_deps(shutit))

	do_lists(shutit)

	# Check for conflicts now.
	errs.extend(check_conflicts(shutit))
	# Cache the results of check_ready at the start.
	errs.extend(check_ready(shutit, throw_error=False))
	if errs:
		shutit.log(shutit_util.print_modules(shutit), level=logging.ERROR)
		child = None
		for err in errs:
			shutit.log(err[0], level=logging.ERROR)
			if not child and len(err) > 1:
				child = err[1]
		shutit.fail("Encountered some errors, quitting", shutit_pexpect_child=child) # pragma: no cover

	do_remove(shutit)
	do_build(shutit)
	do_test(shutit)
	do_finalize(shutit)
	finalize_target(shutit)
	shutit.log(shutit_util.build_report(shutit, '#Module: N/A (END)'), level=logging.DEBUG)
	do_exam_output(shutit)
	shutit_global.shutit_global_object.do_final_messages()

	# Mark the build as completed
	shutit.build['completed'] = True
	shutit.log('ShutIt run finished',level=logging.INFO)
	shutit_util.handle_exit(shutit=shutit, exit_code=0)


def do_lists(shutit):
	if shutit.action['list_deps']:
		cfg = shutit.cfg
		# Show dependency graph
		digraph = 'digraph depgraph {\n'
		digraph += '\n'.join([ make_dep_graph(module) for module_id, module in shutit.shutit_map.items() if module_id in cfg and cfg[module_id]['shutit.core.module.build'] ])
		digraph += '\n}'
		f = open(shutit.build['log_config_path'] + '/digraph.txt','w')
		f.write(digraph)
		f.close()
		digraph_all = 'digraph depgraph {\n'
		digraph_all += '\n'.join([ make_dep_graph(module) for module_id, module in shutit.shutit_map.items() ])
		digraph_all += '\n}'
		fname = shutit.build['log_config_path'] + '/digraph_all.txt'
		f = open(fname,'w')
		f.write(digraph_all)
		f.close()
		shutit.log('\n================================================================================\n' + digraph_all)
		shutit.log('\nAbove is the digraph for ALL MODULES SEEN in this ShutIt invocation. Use graphviz to render into an image, eg\n\n\tcat ' + fname + ' | dot -Tpng -o depgraph.png\n')
		shutit.log('\n================================================================================\n')
		fname = shutit.build['log_config_path'] + '/digraph_this.txt'
		f = open(fname,'w')
		f.write(digraph_all)
		f.close()
		shutit.log('\n\n' + digraph)
		shutit.log('\n================================================================================\n' + digraph)
		shutit.log('\nAbove is the digraph for all modules configured to be built IN THIS ShutIt invocation. Use graphviz to render into an image, eg\n\ncat ' + fname + ' | dot -Tpng -o depgraph.png\n')
		shutit.log('\n================================================================================\n')
		# Exit now
		shutit_util.handle_exit(shutit=shutit)
	# Dependency validation done, now collect configs of those marked for build.
	shutit_util.config_collection_for_built(shutit)


	if shutit.action['list_configs'] or shutit.build['loglevel'] <= logging.DEBUG:
		# Set build completed
		shutit.build['completed'] = True
		shutit.log('================================================================================')
		shutit.log('Config details placed in: ' + shutit.build['log_config_path'])
		shutit.log('================================================================================')
		shutit.log('To render the digraph of this build into an image run eg:\n\ndot -Tgv -o ' + shutit.build['log_config_path'] + '/digraph.gv ' + shutit.build['log_config_path'] + '/digraph.txt && dot -Tpdf -o digraph.pdf ' + shutit.build['log_config_path'] + '/digraph.gv\n\n')
		shutit.log('================================================================================')
		shutit.log('To render the digraph of all visible modules into an image, run eg:\n\ndot -Tgv -o ' + shutit.build['log_config_path'] + '/digraph_all.gv ' + shutit.build['log_config_path'] + '/digraph_all.txt && dot -Tpdf -o digraph_all.pdf ' + shutit.build['log_config_path'] + '/digraph_all.gv\n\n')
		shutit.log('================================================================================')
		shutit.log('\nConfiguration details have been written to the folder: ' + shutit.build['log_config_path'] + '\n')
		shutit.log('================================================================================')
	if shutit.action['list_configs']:
		return


def do_exam_output(shutit):
	if shutit.build['exam_object']:
		test = shutit.build['exam_object']
		test.calculate_score()
		test_output = str(test)
		shutit.log(test_output,level=logging.CRITICAL)
		f = open('/tmp/shutit_exam_output', 'w')
		f.write(test_output)
		f.close()


def do_phone_home(shutit, msg=None,question='Error seen - would you like to inform the maintainers?'):
	"""Report message home.
	msg - message to send home
	question - question to ask - assumes Y/y for send message, else no
	"""
	if msg is None:
		msg = {}
	if shutit.build['interactive'] == 0:
		return
	msg.update({'shutitrunstatus':'fail','pwd':os.getcwd(),'user':os.environ.get('LOGNAME', '')})
	if question != '' and shutit_util.util_raw_input(shutit, prompt=question + ' (Y/n)\n') not in ('y','Y',''):
		return
	try:
		urllib.urlopen("http://shutit.tk?" + urllib.urlencode(msg))
	except Exception as e:
		shutit.log('failed to send message: ' + str(e.message),level=logging.ERROR)


def do_interactive_modules(shutit):
	cfg = shutit.cfg
	errs = []
	while True:
		shutit_util.list_modules(shutit, long_output=False,sort_order='run_order')
		# Which module do you want to toggle?
		module_id = shutit_util.util_raw_input(shutit, prompt='Which module id do you want to toggle?\n(just hit return to continue with build)\n(you can enter a substring if it is uniquely matching)\n')
		if module_id:
			try:
				_=cfg[module_id]
			except NameError:
				matched_to = []
				for m in cfg.keys():
					if re.match('.*'+module_id+'.*',m):
						matched_to.append(m)
				if len(matched_to) > 1:
					print('Please input a uniquely matchable module id. Matches were: ' + str(matched_to))
					continue
				elif len(matched_to) == 0:
					print('Please input a valid module id')
				else:
					module_id = matched_to[0]
			cfg[module_id]['shutit.core.module.build'] = not cfg[module_id]['shutit.core.module.build']
			if not shutit_util.config_collection_for_built(shutit, throw_error=False):
				cfg[module_id]['shutit.core.module.build'] = not cfg[module_id]['shutit.core.module.build']
				shutit_util.util_raw_input(shutit, prompt='Hit return to continue.\n')
				continue
			# If true, set up config for that module
			if cfg[module_id]['shutit.core.module.build']:
				# TODO: does this catch all the ones switched on? Once done, get configs for all those.
				newcfg_list = []
				while True:
					print(shutit_util.print_config(shutit,cfg,module_id=module_id))
					name = shutit_util.util_raw_input(shutit, prompt='Above is the config for that module. Hit return to continue, or a config item you want to update.\n')
					if name:
						doing_list = False
						while True:
							if doing_list:
								val_type = shutit_util.util_raw_input(shutit, prompt='Input the type for the next list item: b(oolean), s(tring).\n')
								if val_type not in ('b','s',''):
									continue
							else:
								val_type = shutit_util.util_raw_input(shutit, prompt='Input the type for that config item: b(oolean), s(tring), l(ist).\n')
								if val_type not in ('b','s','l',''):
									continue
							if val_type == 's':
								val = shutit_util.util_raw_input(shutit, prompt='Input the value new for that config item.\n')
								if doing_list:
									newcfg_list.append(val)
								else:
									break
							elif val_type == 'b':
								val = shutit_util.util_raw_input(shutit, prompt='Input the value new for the boolean (t/f).\n')
								if doing_list:
									if val == 't':
										newcfg_list.append(True)
									elif val == 'f':
										newcfg_list.append(False)
									else:
										print('Input t or f please')
										continue
								else:
									break
							elif val_type == 'l':
								doing_list = True
								newcfg_list = []
							elif val_type == '':
								break
						# TODO: handle blank/None
						if doing_list:
							cfg[module_id][name] = newcfg_list
						else:
							cfg[module_id][name] = val
					else:
						break
			else:
				pass
				# TODO: if removing, get any that depend on it, and remove those too
		else:
			break
	return errs


def setup_signals():
	signal.signal(signal.SIGINT, shutit_util.ctrl_c_signal_handler)
	signal.signal(signal.SIGQUIT, shutit_util.ctrl_quit_signal_handler)

def create_session(session_type='bash'):
	assert session_type in ('bash','docker')
	shutit_global_object = shutit_global.shutit_global_object
	return shutit_global_object.new_session(session_type)

shutit_version='0.9.357'

if __name__ == '__main__':
	setup_signals()
	main()
