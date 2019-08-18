#!/usr/bin/env python
import rospy
import tf
import numpy as np
from tf.transformations import *
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseWithCovarianceStamped
from rtabmap_ros.srv import ResetPose
reset_pose = rospy.ServiceProxy('/rtabmap/reset_odom_to_pose', ResetPose)

n = 0
start = Odometry()
pose_pub = rospy.Publisher('/rtabmap/global_pose', PoseWithCovarianceStamped, queue_size=1)
pub = rospy.Publisher('/gnss_odom_from_start', Odometry, queue_size=1)

def callback_odom(Odom):
    global n
    global start
    gnss_odom = Odometry()
    posi = PoseWithCovarianceStamped()
    if Odom.header.seq == 9365:
        start = Odom
        start.header.frame_id = "map"
        e = tf.transformations.euler_from_quaternion((start.pose.pose.orientation.x, start.pose.pose.orientation.y, start.pose.pose.orientation.z, start.pose.pose.orientation.w))
        reset_pose(0.0, 0.0, 0.0, 0, 0,e[2])
        posi.pose.pose.position.x = 0
        posi.pose.pose.position.y = 0
        posi.pose.pose.orientation = start.pose.pose.orientation
        posi.pose.covariance = [0.00001, 0, 0, 0, 0, 0, 0, 0.00001, 0, 0, 0, 0, 0, 0, 0.000001, 0, 0, 0, 0, 0, 0, 0.000001, 0, 0, 0, 0, 0, 0, 0.000001, 0, 0, 0, 0, 0, 0, 0.000001]
        time_before = rospy.get_time()
        while (rospy.get_time()-time_before) < 1.0:
            pose_pub.publish(posi)
    elif Odom.header.seq > 9365:
        e = tf.transformations.euler_from_quaternion((start.pose.pose.orientation.x, start.pose.pose.orientation.y, start.pose.pose.orientation.z, start.pose.pose.orientation.w))
        yaw = e[2]
        gnss_odom.header.frame_id = "map"
        gnss_odom.pose.pose.position.x = (Odom.pose.pose.position.x - start.pose.pose.position.x)
        gnss_odom.pose.pose.position.y = (Odom.pose.pose.position.y - start.pose.pose.position.y)
        gnss_odom.pose.pose.position.y = (Odom.pose.pose.position.y - start.pose.pose.position.y)
        orientation = quaternion_multiply((Odom.pose.pose.orientation.x,Odom.pose.pose.orientation.y,Odom.pose.pose.orientation.z,Odom.pose.pose.orientation.w), (start.pose.pose.orientation.x,start.pose.pose.orientation.y,start.pose.pose.orientation.z,start.pose.pose.orientation.w)) 
        gnss_odom.pose.pose.orientation.x, gnss_odom.pose.pose.orientation.y, gnss_odom.pose.pose.orientation.z, gnss_odom.pose.pose.orientation.w = orientation[0], orientation[1], orientation[2], orientation[3]
        pub.publish(gnss_odom)
    n = n + 1
    
def listen():
    rospy.Subscriber('/gnss_odom', Odometry, callback_odom)
    rospy.spin()

def main():
    rospy.init_node('set_pose')
    listen()

if __name__ == '__main__':
    main()

