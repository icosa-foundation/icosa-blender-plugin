# <pep8-80 compliant>
import time

from signin import PolySignIn
from importer import Importer

# TODO: replace by the path to your OBJ and MTL file
OBJ_FILE = "/usr/local/google/home/btco/Downloads/cube.obj"
MTL_FILE = "/usr/local/google/home/btco/Downloads/cube.mtl"

def main():
    sign_in = PolySignIn()
    sign_in.authenticate()
    print("Sign in successful.")

    importer = Importer(sign_in.access_token)
    operation = importer.start_obj_import(OBJ_FILE, [MTL_FILE])
    print("Import started successfully. Operation: %s" % operation);
    while not operation.done and not operation.error:
        print("Waiting to poll operation.")
        time.sleep(2)
        print("Polling operation")
        operation = importer.poll_operation(operation)
        print("Operation: %s" % operation)
    if operation.error:
        print("ERROR: %s" % operation.error)
    else:
        print("Operation is DONE. %s" % operation)

if __name__ == "__main__":
    main()

