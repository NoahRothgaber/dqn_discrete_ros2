import gymnasium as gym
import rclpy
from rclpy.node import Node
import yaml
import argparse
from model_msgs.srv import EnvReset
from model_msgs.srv import EnvSetup
from model_msgs.srv import EnvStepCartpole


class RosGymEnvHelper(Node):
    def __init__(self):
        super().__init__('ros_gym_env_helper')
        with open('/home/csrobot/pytorch_ws/src/dqn_discrete_ros2/dqn_discrete_ros2/hyperparameters.yml', 'r') as file:
            all_hyperparameter_sets = yaml.safe_load(file)
            hyperparameters = all_hyperparameter_sets['cartpole1']
        self.hyperparameter_set = 'cartpole1'
        self.is_training = hyperparameters['is_training']
        self.env_id = hyperparameters['env_id']
        self.env_make_params = hyperparameters.get('env_make_params', {})

        
        # also contains the only instance of the environment 
        self.env = gym.make(self.env_id, render_mode=None if self.is_training else 'human', **self.env_make_params)
        self.env.reset()  # Initialize the environment
        # declare new action publisher
        # declare random action subscriber
        # declare state_subscriber
        print("Setup Server")
        self.env_setup_server = EnvSetupServer(self)
        print("Reset Server")
        self.env_reset_server = EnvResetServer(self)
        print("Step Server")
        self.env_step_server = EnvStepServer(self)
        print("done")
        
    def next_step(self, step):
        return self.env.step(step)
        
    
    def reset_env(self):
        self.env.reset()

class EnvResetServer(Node):
    def __init__(self, ros_gym_env_helper):
        super().__init__('env_reset_server')
        self.ros_gym_env_helper = ros_gym_env_helper
        self.srv = self.create_service(EnvReset, 'env_reset', self.reset_callback)
        print("service created")
        # Reset the environment and get the initial state
    def reset_callback(self, request, response):
        self.get_logger().info(f'Recieved {response.reset_request}...')
        print('AGHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH')
        self.ros_gym_env_helper.reset_env()
        response.is_reset = True
        return response

class EnvSetupServer(Node):
    def __init__(self, ros_gym_env_helper):
        super().__init__('env_setup_server')
        self.ros_gym_env_helper = ros_gym_env_helper
        self.srv = self.create_service(EnvSetup, 'env_setup', self.setup_callback)

    def setup_callback(self, request, response):
        response.state_dim = 5
        response.action_dim = 2
        # response.state_dim = self.ros_gym_env_helper.env.observation_space.shape[0]
        # response.action_dim = self.ros_gym_env_helper.env.action_space.n
        self.get_logger().info(f'Sending environment information to agent: state_dim={response.state_dim}, action_dim={response.action_dim}')
        return response    

# class EnvSetupServer(Node):
#     def __init__(self, ros_gym_env_helper):
#         super().__init__('env_setup_server')
#         self.ros_gym_env_helper = ros_gym_env_helper
#         self.srv = self.create_service(EnvSetup, 'env_setup', self.setup_callback)
#         self.get_logger().info("EnvSetup service server is ready")

#     def setup_callback(self, request, response):
#         self.get_logger().info("Received request")
#         try:
#             response.state_dim = self.ros_gym_env_helper.env.observation_space.shape[0]
#             response.action_dim = self.ros_gym_env_helper.env.action_space.n
#             self.get_logger().info(f'Sending response: state_dim={response.state_dim}, action_dim={response.action_dim}')
#         except Exception as e:
#             self.get_logger().error(f"Error processing request: {e}")
#         return response
    
class EnvStepServer(Node):
    def __init__(self, ros_gym_env_helper):
        super().__init__('env_step_server')
        self.ros_gym_env_helper = ros_gym_env_helper
        self.srv = self.create_service(EnvStepCartpole, 'env_step', self.step_callback)

    def step_callback(self, request, response):
        response = self.ros_gym_env_helper.next_step(request)
        return response
#num_actions = env.action_space.n
#num_states = env.observation_space.shape[0]       
#int8 state_dim
#int8 action_dim


def main(args=None):
    rclpy.init(args=args)
    ros_gym_env_helper = RosGymEnvHelper()
    
    # Spin env_setup once to send dimensions of env
    rclpy.spin(ros_gym_env_helper)

    ros_gym_env_helper.destroy_node()

    rclpy.shutdown()
    
if __name__ == '__main__':
    # parser = argparse.ArgumentParser(description='Train or test model.')
    # parser.add_argument('hyperparameters', help='')
    # args = parser.parse_args()
    main()