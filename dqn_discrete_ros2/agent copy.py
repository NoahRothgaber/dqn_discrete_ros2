import gymnasium as gym
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import random
import torch
from torch import nn
import torch.nn.functional as F
import yaml
from collections import deque
from datetime import datetime, timedelta
import argparse
import itertools
import os

import rclpy
from rclpy.node import Node
from model_msgs.srv import EnvReset
from model_msgs.srv import EnvSetup
from model_msgs.srv import EnvStepCartpole

#import flappy_bird_gymnasium

# For printing date and time
DATE_FORMAT = "%m-%d %H:%M:%S"

# Directory for saving run info
RUNS_DIR = "runs"
os.makedirs(RUNS_DIR, exist_ok=True)

# 'Agg': used to generate plots as images and save them to a file instead of rendering to screen
matplotlib.use('Agg')

device = 'cuda' if torch.cuda.is_available() else 'cpu'

class EnvResetClient(Node):
    def __init__(self):
        super().__init__('env_reset_client')
        self.client = self.create_client(EnvReset, 'env_reset')
        while not self.client.wait_for_service(timeout_sec=2.0):
            self.get_logger().info('env reset service not available, waiting again...')
        self.req = self.client.Request()

    def send_request(self, reset_request):
        self.req.reset_request = reset_request
        self.future = self.cli.call_async(self.req)
        rclpy.spin_until_future_complete(self, self.future)
        return self.future.result()

class EnvDimClient(Node):
    def __init__(self):
        super().__init__('env_dim_client')
        self.client = self.create_client(EnvSetup, 'env_setup')
        while not self.EnvDimClient.wait_for_service(timeout_sec=2.0):
            self.get_logger().info('env dimension service not available, waiting again...')
        self.req = self.client.Request()

    def send_request(self, dim_request):
        self.req.dim_request = dim_request
        self.future = self.cli.call_async(self.req)
        rclpy.spin_until_future_complete(self, self.future)
        return self.future.result()

class EnvStepClient(Node):
    def __init__(self):
        super().__init__('env_step_client')
        self.client = self.create_client(EnvStepCartpole, 'env_step')
        while not self.client.wait_for_service(timeout_sec=2.0):
            self.get_logger().info('reset env service not available, waiting again...')
        self.req = self.client.Request() 
    def send_request(self, step_request):
        self.req.step_request = step_request
        self.future = self.cli.call_async(self.req)
        rclpy.spin_until_future_complete(self, self.future)
        return self.future.result()
    
# class EnvStateClient(Node):
#     def __init__(self):
#         super().__init__('env_state_client')
#         self.client = self.create_client(EnvStep, 'env_state')
#         while not self.client.wait_for_service(timeout_sec=2.0):
#             self.get_logger().info('env state service not available, waiting again...')
#         self.req = self.client.Request() 
#     def send_request(self, state_request):
#         self.req.state_request = state_request
#         self.future = self.cli.call_async(self.req)
#         rclpy.spin_until_future_complete(self, self.future)
#         return self.future.result()

        
class ReplayMemory():
    def __init__(self, maxlen, seed=None):
        self.memory = deque([], maxlen=maxlen)
        if seed is not None:
            random.seed(seed)

    def append(self, transition):
        self.memory.append(transition)

    def sample(self, sample_size):
        return random.sample(self.memory, sample_size)

    def __len__(self):
        return len(self.memory)


class DQN(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dim=256):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_dim, hidden_dim)
        self.output = nn.Linear(hidden_dim, action_dim)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        return self.output(x)


# Deep Q-Learning Agent
class Agent(Node):
    def __init__(self, hyperparameter_set):
        with open('hyperparameters.yml', 'r') as file:
            all_hyperparameter_sets = yaml.safe_load(file)
            hyperparameters = all_hyperparameter_sets[hyperparameter_set]

        self.hyperparameter_set = hyperparameter_set
        self.is_training = hyperparameters['is_training']
        self.learning_rate_a = hyperparameters['learning_rate_a']
        self.discount_factor_g = hyperparameters['discount_factor_g']
        self.network_sync_rate = hyperparameters['network_sync_rate']
        self.replay_memory_size = hyperparameters['replay_memory_size']
        self.mini_batch_size = hyperparameters['mini_batch_size']
        self.epsilon_init = hyperparameters['epsilon_init']
        self.epsilon_decay = hyperparameters['epsilon_decay']
        self.epsilon_min = hyperparameters['epsilon_min']
        self.stop_on_reward = hyperparameters['stop_on_reward']
        self.fc1_nodes = hyperparameters['fc1_nodes']
        # self.env_make_params = hyperparameters.get('env_make_params', {})
        self.loss_fn = nn.MSELoss()
        self.optimizer = None
        self.env_dim_client = EnvDimClient()
        self.reset_client = EnvResetClient()
        self.step_client = EnvStepClient()

        dim_message = self.env_dim_client.send_request()

        self.action_space_dim = dim_message.action_dim
        self.state_dim = dim_message.state_dim
        
        self.LOG_FILE = os.path.join(RUNS_DIR, f'{self.hyperparameter_set}.log')
        self.MODEL_FILE = os.path.join(RUNS_DIR, f'{self.hyperparameter_set}.pt')
        self.GRAPH_FILE = os.path.join(RUNS_DIR, f'{self.hyperparameter_set}.png')
        
    def run(self, is_training=True, render=False):
        if is_training:
            start_time = datetime.now()
            last_graph_update_time = start_time
            log_message = f"{start_time.strftime(DATE_FORMAT)}: Training starting..."
            print(log_message)
            with open(self.LOG_FILE, 'w') as file:
                file.write(log_message + '\n')

        #env = gym.make(self.env_id, render_mode='human' if render else None, **self.env_make_params)
        #num_actions = env.action_space.n
        #num_states = env.observation_space.shape[0]
        rewards_per_episode = []
        policy_dqn = DQN(self.state_dim, self.action_space_dim, self.fc1_nodes).to(device)

        if is_training:
            epsilon = self.epsilon_init
            memory = ReplayMemory(self.replay_memory_size)
            target_dqn = DQN(self.state_dim, self.action_space_dim, self.fc1_nodes).to(device)
            target_dqn.load_state_dict(policy_dqn.state_dict())
            self.optimizer = torch.optim.Adam(policy_dqn.parameters(), lr=self.learning_rate_a)
            epsilon_history = []
            step_count = 0
            best_reward = -9999999
        else:
            policy_dqn.load_state_dict(torch.load(self.MODEL_FILE))
            policy_dqn.eval()

        for episode in itertools.count():
            # reset env
            # grab state from topic
            self.reset_client.send_request()

            state = self.state_subscriber.step_data()
            state = torch.tensor(state, dtype=torch.float, device=device)
            terminated = False
            episode_reward = 0.0

            while not terminated and episode_reward < self.stop_on_reward:
                if is_training and random.random() < epsilon:
                    action = random.sample(self.action_space_dim)
                    #action = torch.tensor(action, dtype=torch.int64, device=device)
                else:
                    with torch.no_grad():
                        action = policy_dqn(state.unsqueeze(dim=0)).squeeze().argmax()
                        action = action.item()

                #new_state, reward, terminated, truncated, info = env.step(action.item())

                
                #receive step from service
                state_srv = self.step_client.send_request(action)
                state = np.array([state_srv.cart_pos, state_srv.cart_velocity, state_srv.pole_angle, state_srv.pole_angular_velocity])
                # Converts current state information for cartpole into a numpy array to match formatting used by Agent without ROS
                self.step_data = (state, state_srv.reward, state_srv.terminated, state_srv.truncated)
                new_state, reward, terminated, truncated = self.step_data
                episode_reward += reward
                new_state = torch.tensor(new_state, dtype=torch.float, device=device)
                reward = torch.tensor(reward, dtype=torch.float, device=device)
                action = torch.tensor(action, dtype=torch.int64, device=device)
                
                if is_training:
                    memory.append((state, action, new_state, reward, terminated, truncated))
                    step_count += 1

                state = new_state

            rewards_per_episode.append(episode_reward)

            if is_training:
                if episode_reward > best_reward:
                    log_message = f"{datetime.now().strftime(DATE_FORMAT)}: New best reward {episode_reward:0.1f} ({(episode_reward-best_reward)/best_reward*100:+.1f}%) at episode {episode}, saving model..."
                    print(log_message)
                    with open(self.LOG_FILE, 'a') as file:
                        file.write(log_message + '\n')
                    torch.save(policy_dqn.state_dict(), self.MODEL_FILE)
                    best_reward = episode_reward

                current_time = datetime.now()
                if current_time - last_graph_update_time > timedelta(seconds=10):
                    self.save_graph(rewards_per_episode, epsilon_history)
                    last_graph_update_time = current_time

                if len(memory) > self.mini_batch_size:
                    mini_batch = memory.sample(self.mini_batch_size)
                    self.optimize(mini_batch, policy_dqn, target_dqn)
                    epsilon = max(epsilon * self.epsilon_decay, self.epsilon_min)
                    epsilon_history.append(epsilon)
                    if step_count > self.network_sync_rate:
                        target_dqn.load_state_dict(policy_dqn.state_dict())
                        step_count = 0
            # Service to signal an epsiode has ended so we can reset the state
            # "waiting for new episode"
            client = EnvResetClient()
            response = client.send_request("Environment Reset Request")
            client.get_logger().info(f'Response for {response.reset_request}: is_reset {response.is_reset}')


    def save_graph(self, rewards_per_episode, epsilon_history):
        fig = plt.figure(1)
        mean_rewards = np.zeros(len(rewards_per_episode))
        for x in range(len(mean_rewards)):
            mean_rewards[x] = np.mean(rewards_per_episode[max(0, x-99):(x+1)])
        plt.subplot(121)
        plt.ylabel('Mean Rewards')
        plt.plot(mean_rewards)
        plt.subplot(122)
        plt.ylabel('Epsilon Decay')
        plt.plot(epsilon_history)
        plt.subplots_adjust(wspace=1.0, hspace=1.0)
        fig.savefig(self.GRAPH_FILE)
        plt.close(fig)

    def optimize(self, mini_batch, policy_dqn, target_dqn):
        states, actions, new_states, rewards, terminations = zip(*mini_batch)
        states = torch.stack(states)
        actions = torch.stack(actions)
        new_states = torch.stack(new_states)
        rewards = torch.stack(rewards)
        terminations = torch.tensor(terminations).float().to(device)

        with torch.no_grad():
            target_q = rewards + (1-terminations) * self.discount_factor_g * target_dqn(new_states).max(dim=1)[0]

        current_q = policy_dqn(states).gather(dim=1, index=actions.unsqueeze(dim=1)).squeeze()
        loss = self.loss_fn(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train or test model.')
    parser.add_argument('hyperparameters', help='')
    parser.add_argument('--train', help='Training mode', action='store_true')
    args = parser.parse_args()
    dql = Agent(hyperparameter_set=args.hyperparameters)
    if args.train:
        dql.run(is_training=True)
    else:
        dql.run(is_training=False, render=True)
