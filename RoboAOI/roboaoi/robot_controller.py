 
import subprocess
import os


class RobotController:
    """
    Executes the Genesis robot simulation.

    If Genesis is unavailable (e.g. local Windows machine),
    the dashboard continues running without crashing.
    """

    def execute(self, status):

        print("\n==============================")
        print("Robot Controller")
        print("==============================")

        if status == "PASS":
            print("PCB PASSED inspection.")
            print("Robot Action : Move to Conveyor")

        else:
            print("PCB FAILED inspection.")
            print("Robot Action : Move to Reject Bin")

        print("\nLaunching Genesis robot...\n")

        script = os.path.join(
            "franka_fruit_pick",
            "grasp_demo.py"
        )

        try:

            subprocess.run(
                [
                    "python",
                    script,
                    "--save-frames",
                ],
                check=True,
            )

            print("\nRobot task completed.")

        except FileNotFoundError:
            print("\nGenesis script not found.")
            print("Skipping robot simulation.")

        except subprocess.CalledProcessError as e:
            print("\nGenesis is unavailable on this machine.")
            print("Skipping robot simulation.")
            print(f"Reason: {e}")

        except Exception as e:
            print("\nUnexpected robot controller error.")
            print(e)