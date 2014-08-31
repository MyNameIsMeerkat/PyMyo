
###############################################################################
## File       :  test_aysnc.py
## Description:  Async test command module for pymyo
##            :  
## Created_On :  Tue Sep 25 18:10:08 2014
## Created_By :  Rich Smith (rich@etsy.com)
## Modified_On:  Tue Sep 25 18:10:08 2014
## Modified_By:  Rich Smith (rich@etsy.com)
## License    :  BSD-3
##
##
###############################################################################
__author__  = "rich@etsy.com"
__version__ = 1.0
__updated__ = "24/08/2014"
__help__    = "Test async module for showing structure"
__alias__   = ["ta", "t3st_a5ync"]
__async__   = True

import time


def Command(pymyo, name, cmd_id, *args):

    time.sleep(10.0)
    ret_msg = "%s returned %d\nThe reference back to the pymyo instance is: %s"%(name, cmd_id, pymyo)
    if args:
        ret_msg += "\nThe arguments passed were %s"%(args)

    pymyo.async_exit(cmd_id, ret_msg)