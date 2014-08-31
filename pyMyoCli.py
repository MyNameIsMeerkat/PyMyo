__version__ = 0.1
__author__  = "rich@kyr.us"

import os
import cmd
import sys
import code
import time
import Queue
import readline
import traceback
from threading import Thread

from _pyMyo import pyMyo

##Command completion for OS X requires this as it doesn't use gnu readline
if 'libedit' in readline.__doc__:
    readline.parse_and_bind("bind ^I rl_complete")
    
else:
    readline.parse_and_bind("tab: complete")

##Stop overly large histories    
readline.set_history_length(1000)

##Try for iPython support
#ToDo - make supported shells / consoles modular in a /shells subdir ?
try:
    from IPython import embed
    ipy_support = True
    
except ImportError:
    print "[-] IPython support seems unavailable"
    ipy_support = False
    
##The absolute location of this file
MODULE_LOCATION = os.path.abspath(os.path.dirname(__file__))

class pyMyoCli(pyMyo, cmd.Cmd):
    """
    General CLI/Shell wrapper for the invocation of modules that
    help with a whole variety of nifty things
    """ 
    def __init__(self):
        """
        Set some defaults
        """
        ##Init pyMyo - super does not work correctly ......
        pyMyo.__init__(self)

        ##Init parser loop
        cmd.Cmd.__init__(self)
        
        ##Defaults
        self.prev_arg            = ""
        self.shotcuts            = ["!", ">", "=", "$"]
        self.autoarg_exceptions  = ["help", "console", "shell"]

        if self.banner:

            self.intro = """
   ___       \033[35m__  ___\033[0m
  / _ \__ __\033[35m/  |/  /_ _____\033[0m
 / ___/ // \033[35m/ /|_/ / // / _ \\\033[0m
/_/   \\_, \033[35m/_/  /_/\\_, /\\___/\033[0m
     /___/       \033[35m/___/\033[0m"""+" v %s\n"%(__version__)

        ##For tab-completion logic
        self.command_that_take_module_as_args = ["help", "info"]

        ##Result queue for async commands, swept in the postloop
        self.async_ret_q = Queue.Queue(0)

        ##A table to track async command threads
        self.async_cmd_threads = {}

        ##A table to hold the status of asynchronous commands
        self.async_cmd_status  = {}

        ##Incrementor for a unique id for each command
        self.cmd_id = 0


    def _main(self):
        """
        Just call the cmdloop method in cmd module
        """
        return self.cmdloop() 
    
    
    def _save_history(self, history_file):
        """
        Save the commandline history to the readline history provided
        + Clear the history buffer
        """
        readline.write_history_file(os.path.join(MODULE_LOCATION, history_file))
        readline.clear_history()  
        
    
    def _load_history(self, history_file):
        """
        Load a previously saved readline history file 
        """
        try:
            readline.read_history_file(os.path.join(MODULE_LOCATION, history_file))
        except IOError:
            pass    
        
        
    def _swap_history(self, old_history, new_history):
        """
        Save old history and swap to new history
        """
        self._save_history(old_history)
        self._load_history(new_history)
    
    
    def cmdloop(self, intro = None):
        """
        Overload cmdloop to allow a cleaner way for us to actually reload the pymyo instance
        at run time to allow nicer dev cycles
        """
        cmd.Cmd.cmdloop(self, self.intro)

        return self.reload_pymyo
    
    
    def preloop(self):
        """
        Retrieve previous history before we kick off the main loop
        """
        try:
            readline.read_history_file(os.path.join(MODULE_LOCATION, ".pymyo.history"))
        except IOError:
            pass 
        
        self.load_modules()
        self.populate_aliases()
        #self.populate_help()
        #self.populate_autocomplete()
        
        
    def postloop(self):
        """
        Save the history before we exit
        """
        ##Save history
        readline.write_history_file(os.path.join(MODULE_LOCATION, ".pymyo.history"))
        
        
    def postcmd(self, stop, line):
        """
        Do housekeeping after each command
        """
        ##Store the previous argument for quick auto retrevial in future commands
        line = line.strip()
        self.prev_arg = ''.join(line.split(" ")[1:])

        return stop


    def precmd(self, line):
        """
        Hook to add previous argument to current command if no arg is given 
        (and the command isn't on an exception list)
        """
        # line = line.strip()
        # if len(line) and len( line.split(" ")) <2 and line[0] not in self.shotcuts and line.split(" ")[0] not in self.autoarg_exceptions and not line[0].isdigit():
        #     line = "%s %s"%(line, self.prev_arg)
        #


        ##Check whether any asynchronous commands have returned
        try:
            cmd_id, ret_data = self.async_ret_q.get(False)

        except Queue.Empty:
            ##No data returned from cmd threads, all good
            return line

        except Exception, err:
            self.output(self.ruler*70)
            self.error("Bad data given in return queue by asynchronous module '%s' "%(line))
            self._error()
            self.output(self.ruler*70)
            return line

        ##Get the thread object form the table
        t = self.async_cmd_threads.get(cmd_id, False)
        if not t:
            self.output(self.ruler*70)
            self.error("Unknown asynchronous command ID '%s'? "%(cmd_id))
            self._error()
            self.output(self.ruler*70)
            return line

        ##Join the worker thread & remove from the cmd table
        ## + update the status table for the command
        self.async_ret_q.task_done()
        t.join()
        del self.async_cmd_threads[cmd_id]
        self.async_cmd_status[cmd_id][0] = True
        self.async_cmd_status[cmd_id][2] = time.time()
        self.async_cmd_status[cmd_id][3] = ret_data
        self.notify("Return data from async command %d avaiable (type: `results` to view)\n"%(cmd_id))
            
        return line
        
        
    def parseline(self, line):
        """
        Override the standard parseline method to allow us to alias '#' to "do_py"
        in the same way "!" is aliased to "do_shell"
        """
        line = line.strip()
        if not line:
            return None, None, line
        elif line[0] == '?':
            line = 'help ' + line[1:]
            
        elif line[0] == "=":
            if hasattr(self, 'do_eval'):
                line = 'eval ' + line[1:]
            else:
                return None, None, line 
            
        elif line[0] == ">":
            if hasattr(self, 'do_ipyconsole') and self.use_ipy and ipy_support:
                line = 'ipyconsole ' + line[1:]
            elif hasattr(self, 'do_console'):
                line = 'console ' + line[1:]
            else:
                return None, None, line         
            
        elif line[0] == '$':
            if hasattr(self, 'do_ishell'):
                line = 'ishell ' + line[1:]
            else:
                return None, None, line
            
        elif line[0] == '!':
            if hasattr(self, 'do_shell'):
                line = 'shell ' + line[1:]
            else:
                return None, None, line
        i, n = 0, len(line)
        while i < n and line[i] in self.identchars: i = i+1
        cmd, arg = line[:i], line[i:].strip()
        return cmd, arg, line            
        
        
    def async_exit(self, cmd_id, return_msg):
        """
        Method called by asynchronous modules to pass their results
        back to the CLI loop - more a convenience method, just wraps
        a Queue put
        """
        self.async_ret_q.put((cmd_id, return_msg))


    def _update_prompt(self, prompt):
        """
        Update the commandline prompt
        """
        self.prompt = prompt


    def do_py(self, line):
        """
        Execute python expression 
        """
        try:
            exec(line)
        except:
            self.output(  "[-] Error executing expression '%s' "%(line) )
            traceback.print_exc()
            self.output( self.ruler*70 )
    
    
    def do_eval(self, line):    
        """
        Evaluate python expression (also accessed via `= expr` )
        """
        try:
            self.output( eval(line) )
        except:
            self.output( "[-] Error evaluating expression '%s' "%(line) )
            traceback.print_exc()
            self.output( self.ruler*70 )        
            
            
    def do_ipyconsole(self, line):
        """
        Drop to an IPython interactive shell 
        """
        #TODO - support saving ipython history between sessions ....
        if not ipy_support:
            print "[-] IPython dependencies not avaialble, please install IPython"
            return None
        
        ##Save the pyMyo and the python console histories
        self._save_history(".pymyo.history")

        ##Start the embedded IPython console - ctrl-d to exit
        embed()
    
        ##Restore previous pyMyo history
        self._load_history(".pymyo.history")
    
    
    def do_console(self, line):
        """
        Drop to a python interactive shell (also accessed via `> expr` )
        (Ctrl-D to exit by to pyMyo)
        """        
        ##Swap the pyMyo and the python console histories
        self._swap_history(".pymyo.history", ".pymyo_console.history")
        
        console = code.InteractiveConsole()
        banner = "** \033[35mPress Ctrl-D to exit back to the pyMyo shell\033[0m **\n"
        banner += "Python %s on %s"%(sys.version, sys.platform)
        console.runsource("import sys;sys.ps1='%s >>> '"%(self.prompt.split(" ")[0]))
        console.interact(banner)
        
        ##Save console history and Restore previous pyMyo history
        self._swap_history(".pymyo_console.history", ".pymyo.history")
        
        
    def do_shell(self, line):
        """
        Run a shell command (also accessed via `! cmd` )
        """
        print os.popen(line).read()        
        
    
    def do_ishell(self, line):
        """
        Drop to interactive system shell (also accessed via `$` )
        (Ctrl-D to exit by to pyMyo)
        """        
        ##Swap the pyMyo and the system shell histories
        readline.write_history_file(os.path.join(MODULE_LOCATION, ".pymyo.history"))
        readline.clear_history()

        print "** \033[35mPress Ctrl-D to exit back to the pyMyo shell\033[0m **\n"
        os.system(self.shell) 
        
        try:
            readline.read_history_file(os.path.join(MODULE_LOCATION, ".pymyo.history"))
        except IOError:
            pass          
      
        
    def do_list(self, line):
        """
        List available pyMyo modules
        """
        am = self.available_modules.keys()
        am.sort()
        
        ##Pretty print into columns
        longest_name = 0
        for m in am:
            if len(m) > longest_name:
                longest_name = len(m)
        
        print "Module %s Aliases"%(" "*(longest_name-5))
        print "------ %s -------"%(" "*(longest_name-5))
        for m in am:
            print "%s %s- %s"%(m, " "*(longest_name-len(m)), ', '.join(self.available_modules[m].__alias__))
            
        
    def do_info(self, line):
        """
        Display metadata about a specified module
        """
        split_line = line.split(" ")

        if split_line[0] == '':
            self.output("Supply a module name to get info on it:  `info <module_name>`")
            return None

        info_dict = self.get_module_info(split_line[0])
        if not info_dict:
            self.output("No info available for %s "%(split_line[0]))
        
        else:
            self.output("Info for %s module:\n"%(split_line[0]))
            
            for key, value in info_dict.items():
                
                self.output("%s - %s"%(key, value))
        
    
    def do_reload(self, line):
        """
        Call the reload routine to reload all pyMyo modules
        """
        self.reload_modules()
        
        ##Cause the cmdloop to exit so the pymyo class itself can be reinistantiated to take account of
        ## any changes in the reloaded pymyo module
        return True


    def do_debug(self, line):
        """
        Turn debugging on/off
        """
        self.change_debug_state()
        self.output("Debugging = %s"%(self.debug))


    def do_new_module(self, line):
        """
        Create a skeleton directory for a new module - will then need to be hand coded
        """
        #todo


    def do_set(self, line):
        """
        Set an internal var that has been whitelisted as being 'setable'
        Also mangles the name of the variable being set to '_var_<name>'
        to stop any inadvertent setting of critical vars
        """
        line = line.lower().replace(" ","")
        split_line = line.split("=")
        if len(split_line) <2:
            return None
        var = split_line[0]
        val = split_line[1]

        ##Is the var even settable?
        if not self.set_var(var, val):
            print "[-] '%s' is not settable"%(var)
        else:
            print "[+] Setting %s to %s"%(var, val)


    def do_get(self, line):
        """
        Countepart to do_set that can retrieve the mangled user set variable name
        If requested variable is not present None is returned
        """
        split_line = line.split(" ")
        ret = self.get_var(split_line[0])
        if not ret:
            print "[-] Unknown variable '%s'"%(split_line[0])
        else:
            for var, val in ret.items():
                print "%s = %s"%(var, val)


    def do_r(self, line):
        """
        Alias for results
        """
        self.do_results(line)


    def do_results(self, line):
        """
        View returned data from asynchronous commands
        """
        split_line = line.split(" ")
        cmd_id = split_line[0]

        if cmd_id == '':
            ##Show a list of all commands with pending data
            if len(self.async_cmd_status) == 0:
                self.notify("No results pending")
                return None

            for cmd_id, info in self.async_cmd_status.items():

                self.output("\t[ID]\t[Name]\t\t[Status]")
                self.output("\t============================================================================")
                if not info[0]:
                    status = "Command running... (since %s)"%(time.ctime(info[2]))
                else:
                    status = "Completed. (completed %s)"%(time.ctime(info[2]))
                self.output("\t[%d]\t%s\t%s"%(cmd_id, info[1], status))
                self.output("\n\tType `results <cmd_id>` to view output")
                return None

        info = self.async_cmd_status.get(int(cmd_id), False)
        if not info:
            self.error("Unknown command ID given - %s"%(cmd_id))

        elif not info[0]:
            self.notify("\tCommand not completed yet.")
        else:
            self.output("Results from [%s] %s:\n"%(cmd_id, info[1]))
            self.output("%s"%(info[3]))

    ##Tab-completion logic
    def completedefault(self, text, line, begidx, endidx):
        """
        Do the dance to enable tab-complete of a pyMyo module after a command that expects a module
        name as an arg e.g. info
        """
        ##Only do this sub module complete for certain commands
        if line.split(" ")[0] not in self.command_that_take_module_as_args:
            return None

        line = line.split(" ")[1]
        return self.completenames(text, line, begidx, endidx, include_cmd_completes = False)


    def completenames(self, text, line, begidx, endidx, include_cmd_completes = True):
        """
        Do the dance to enable tab-complete of a pyMyo module names bare on the commandline as is needed
        to run such a module
        """
        ##Get possible commands to tabcomplete?
        if include_cmd_completes:
            dotext = 'do_'+text
            cmd_complete_list = [a[3:] for a in self.get_names() if a.startswith(dotext)]
        else:
            cmd_complete_list = []

        ##Get possible module names to tabcomplete
        offs = len(line) - len(text)
        module_complete_list = [s[offs:] for s in self.available_modules.keys() if s.startswith(line)]
        return cmd_complete_list + module_complete_list
    ##//Tab-completion logic

    
    def default(self, line):
        """
        Run a pyMyo module either synchronously or asynchronously
        
        This is the catchall that is used when the input command doesn't match any of the hardcoded
         commands above. We then try and import a module of the specified name from the 'modules'
         dir. This allows for simple extension without having to modify the core pyMyo class.
        """
        ##Call a module or do a calculation ? - check if first char is a digit if so do a calc
        if line[0].isdigit():
            self.do_eval(line)
            return None
            
        spl = line.split(" ")
        try:
            ##Attempt to find a given module via it's name or alias
            module_name = spl[0]
            module_obj = self.get_module(module_name)
            
            if module_obj:
                ##First test to see if the module is a multiprocessing module, if so launch the module in
                ## a new thread
                if getattr(module_obj, "__async__", False):
                    t = Thread(target=module_obj.Command, args=(self,  module_name, self.cmd_id, spl[1:]))
                    self.async_cmd_threads[self.cmd_id] = t
                    self.async_cmd_status[self.cmd_id] = [False, module_name, time.time(), ""]
                    t.start()
                    data = None
                    self.output("%s launched as a asynchronous command - ID: %s"%(spl[0], self.cmd_id))

                else:
                    ##If it's not treat it as a serial module & just run module.<supplied command name>(args)
                    data = getattr(module_obj, "Command")(self, module_name, *spl[1:])
                    self.output("")

                self.cmd_id += 1
                return data
            
        except Exception, err:
            self.output( self.ruler*70 )
            self.error("Error executing command '%s' "%(line))
            self._error()
            self.output( self.ruler*70 )
            

    def do_EOF(self, arg):
        """
        Catch ctrl-d
        """
        self.output("\nCtrl-D caught. Exiting")
        return self.do_exit
    
    def exit(self, arg):
        """
        Quit the shell
        """
        ##call pyMyo cleanup routines
        self.cleanup()

        return True

    def do_exit(self, arg):
        """
        Quit the shell
        """
        ##Child threads still running?
        if len(self.async_cmd_threads) > 0:
            self.output("\nAsynchronous commands still running, waiting for them to complete....")

        return self.exit()
    
    def do_quit(self, arg):
        """
        Quit the shell
        """
        return self.do_exit()
    
    def do_q(self, arg):
        """
        Quit the shell
        """
        return self.do_exit()
    
     
    def output(self, msg):
        """
        Print output to stdout in the CLI
        """
        #TODO take a iterable/json instead of a string ?
        print msg
        
        
    def notify(self, msg):
        """
        Print message to stdout in the CLI with a "[!]" prepended
        """
        #TODO take a iterable/json instead of a string ?
        print "[!] %s"%(msg)
        
        
    def error(self, msg):
        """
        Print error to stdout in the CLI with a "[-]" prepended
        """
        #TODO take a iterable/json instead of a string ?
        print "[-] %s"%(msg)
        
        ##Call the main error class to do traceback prints etc if debugging enabled
        self._error()
        
        
if __name__ == "__main__":
    
    try:
        ##Kick off the interpreter loop
        pmc = pyMyoCli()
        pmc()
        
    except KeyboardInterrupt:
        print "Ctrl-C caught. Exiting"
        pmc.postloop()
